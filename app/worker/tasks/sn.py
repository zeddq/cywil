import asyncio
import json
from pathlib import Path
import sys
import functools
import hashlib
import uuid
from deepdiff import DeepDiff
from typing import Any, Awaitable, Callable, Coroutine, TypeVar
import dateparser
import openai
from dotenv import load_dotenv
from qdrant_client import AsyncQdrantClient, models
from sentence_transformers import SentenceTransformer
from sqlalchemy import select, Result, Select, Tuple, delete
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).parent.parent.parent.parent))

load_dotenv()

from app.core.config_service import get_config
from app.models import SNRulingBase, SNRuling

# --- CONFIGURATION ---
config = get_config()
QDRANT_URL = config.qdrant.url
DATABASE_URL = config.postgres.async_url
OPENAI_API_KEY = config.openai.api_key.get_secret_value()
OPENAI_MODEL = config.openai.summary_model
EMBEDDING_MODEL = "Stern5497/sbert-legal-xlm-roberta-base"
QDRANT_COLLECTION_NAME = config.qdrant.collection_rulings
JSONL_DIR = config.storage.get_path(config.storage.jsonl_dir)


# --- DATABASE SETUP ---

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set. Please add it to your .env file.")

engine = create_async_engine(DATABASE_URL)

# --- CLIENTS ---
aclient = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
qdrant_client = AsyncQdrantClient(url=QDRANT_URL)
embedding_model = SentenceTransformer(EMBEDDING_MODEL)


async def with_session(func: Callable[[AsyncSession], Awaitable[Any]]) -> Awaitable[Any]:
    async with sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        try:
            return await func(session)
        except Exception as e:
            print(f"Failed to process: {e}")
            await session.rollback()
            raise e
        
T = TypeVar('T')
def limit_concurrency(max_in_flight: int) -> Callable[[Callable[..., Awaitable[T]]],
                                                      Callable[..., Awaitable[T]]]:
    """
    Return a decorator that limits concurrent entries
    to `max_in_flight` using an asyncio.Semaphore.
    """
    sem = asyncio.Semaphore(max_in_flight)      # created once

    def decorator(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            async with sem:                     # acquire/release automatically
                return await func(*args, **kwargs)

        return wrapper

    return decorator

@limit_concurrency(max_in_flight=10)
async def process_sn_ruling_file(line: str, session: AsyncSession):
    """Processes a single JSONL SN Ruling file."""    
    print(f"Processing {line}...")
    ruling = SNRulingBase.model_validate_json(line)

    sn_ruling_name = ruling.name
    result_db = await session.execute(select(SNRuling).where(SNRuling.name == sn_ruling_name))
    result = result_db.scalars().first()
    id = None
    if result:
        if DeepDiff(ruling.paragraphs, result.paragraphs) == {} and DeepDiff(ruling.meta, result.meta) == {}:
            print(f"SN Ruling '{sn_ruling_name}' already exists in the database but has different content. Updating.")
            id = result.id
        else:
            print(f"SN Ruling '{sn_ruling_name}' already exists in the database and has the same content. Skipping.")
            return
    else:
        print(f"SN Ruling '{sn_ruling_name}' does not exist in the database. Adding.")
    
    for idx, para in enumerate(ruling.paragraphs):
        embedding = embedding_model.encode(para["text"]).tolist()
        para_id = f"{sn_ruling_name}-{para.get('para_no', idx)}"
        qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha1(para_id.encode()).hexdigest()))
        date_int = 0
        try:
            if ruling and ruling.meta['date']:
                date_int = int(dateparser.parse(ruling.meta['date'], languages=['pl']).strftime("%Y%m%d"))
            else:
                raise ValueError(f"No date found for '{para_id}'")
        except Exception:
            print(f"Failed to parse date for '{para_id}': '{ruling.meta['date']}'")

        print(f"Upserting '{para_id}' to Qdrant with ID {qdrant_id}")
        await qdrant_client.upsert(
            collection_name=QDRANT_COLLECTION_NAME,
            points=[
                models.PointStruct(
                    id=qdrant_id,
                    vector=embedding,
                    payload={"name": para_id,
                             "text": para["text"],
                             "section": para["section"],
                             "para_no": para["para_no"],
                             "entities": para["entities"],
                             **ruling.meta,
                             "date": date_int,
                             },
                )
            ],
            wait=True,
            ordering=models.WriteOrdering.MEDIUM,
        )
        print(f"  -> Upserted '{para_id}' to Qdrant with ID {qdrant_id}")
        
        data_fields = {
            "name": models.PayloadSchemaType.KEYWORD,
            "section": models.PayloadSchemaType.KEYWORD,
            "para_no": models.PayloadSchemaType.INTEGER,
            "docket": models.PayloadSchemaType.KEYWORD,
            "date": models.PayloadSchemaType.INTEGER,
            "panel": models.PayloadSchemaType.TEXT,
            "text": models.PayloadSchemaType.TEXT,
        }

        # Create additional metadata indexes
        for field, field_type in data_fields.items():
            try:
                await qdrant_client.create_payload_index(
                    collection_name=QDRANT_COLLECTION_NAME,
                    field_name=field,
                    field_schema=field_type,
                )
                print(f"Created index for field: {field}")
            except Exception as e:
                print(f"Index for {field} may already exist: {e}")

    sn_ruling_entry = SNRuling(
        qdrant_id=qdrant_id,
        name=sn_ruling_name,
        paragraphs=ruling.paragraphs,
        meta=ruling.meta,
    )
    if id:
        sn_ruling_entry.id = id
    await session.merge(sn_ruling_entry)
    print(f"  -> Added '{sn_ruling_name}' to PostgreSQL.")
    await session.commit()
    print(f"  -> Committed changes to PostgreSQL.")

async def delete_sn_ruling(session: AsyncSession):
    await session.execute(delete(SNRuling))
    await session.commit()

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Process Polish Supreme Court rulings with o3/o1 enhanced pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--input-file", 
        type=Path, 
        default=Path("data/jsonl/final_sn_rulings.jsonl"),
        help="Path to the JSONL file containing the SN rulings"
    )
    parser.add_argument("--force", action="store_true", help="Force re-ingestion of all rulings")
    
    args = parser.parse_args()
    try:
        await qdrant_client.get_collection(collection_name=QDRANT_COLLECTION_NAME)
        print(f"Qdrant collection '{QDRANT_COLLECTION_NAME}' already exists.")
    except Exception:
        print(f"Creating Qdrant collection '{QDRANT_COLLECTION_NAME}'...")
        embedding_size = embedding_model.get_sentence_embedding_dimension()
        await qdrant_client.recreate_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=embedding_size, distance=models.Distance.COSINE),
        )

    if not args.input_file.is_file():
        raise ValueError(f"Input file {args.input_file} is not a file.")

    if args.force:
        await qdrant_client.delete_collection(collection_name=QDRANT_COLLECTION_NAME)
        embedding_size = embedding_model.get_sentence_embedding_dimension()
        await qdrant_client.recreate_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=embedding_size, distance=models.Distance.COSINE),
        )
        await with_session(delete_sn_ruling)

    tasks = []
    async with asyncio.TaskGroup() as tg:
        with open(args.input_file, "r") as f:
            for line in f:
                tasks.append(tg.create_task(with_session(functools.partial(process_sn_ruling_file, line))))

    print("SN Ruling ingestion pipeline finished.")


if __name__ == "__main__":
    print(
        "NOTE: This script defines a new 'SN Ruling' table. "
        "Please create and apply a database migration using Alembic before running this script."
    )
    asyncio.run(main())
