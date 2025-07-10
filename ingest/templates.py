import asyncio
import json
from pathlib import Path
import sys
import functools
import hashlib
import uuid
from typing import Any, Awaitable, Callable

import openai
from dotenv import load_dotenv
from qdrant_client import QdrantClient, models
from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

sys.path.append(str(Path(__file__).parent.parent))

load_dotenv()

from app.config import settings
from app.models import FormTemplate

# --- CONFIGURATION ---
QDRANT_URL = f"http://{settings.qdrant_host}:{settings.qdrant_port}"
DATABASE_URL = settings.database_url
OPENAI_API_KEY = settings.openai_api_key
OPENAI_MODEL = settings.openai_summary_model
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
QDRANT_COLLECTION_NAME = "form_templates"
TEMPLATES_DIR = Path(settings.pdfs_dir) / "templates"


# --- DATABASE SETUP ---

if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is not set. Please add it to your .env file.")

engine = create_async_engine(DATABASE_URL)

# --- CLIENTS ---
aclient = openai.AsyncOpenAI(api_key=OPENAI_API_KEY)
qdrant_client = QdrantClient(url=QDRANT_URL)
embedding_model = SentenceTransformer(EMBEDDING_MODEL)


async def generate_summary(template_text: str, file_name: str) -> str:
    """Generates a short summary for a form template using OpenAI."""
    print(f"Generating summary for {file_name}...")
    
    system_prompt = f"""Create a short, one-sentence summary in Polish for the user-provided Polish legal form template.
    Double-square-brackets denote the input fields of the form. The summary should concisely describe the purpose of the form."""
    
    user_prompt = f"""Filename for context: {file_name}
    Template content (first 2000 chars):
    ---
    {template_text[:2000]}"""

    try:
        completion = await aclient.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        summary = completion.choices[0].message.content.strip()
        print(f"  -> Summary for {file_name}: {summary}")
        return summary
    except Exception as e:
        print(f"Error generating summary for {file_name}: {e}")
        return f"Nie udało się wygenerować podsumowania dla {file_name}."

async def with_session(func: Callable[[AsyncSession], Awaitable[Any]]) -> Awaitable[Any]:
    async with sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)() as session:
        try:
            return await func(session)
        except Exception as e:
            print(f"Failed to process: {e}")
            await session.rollback()
            raise e

async def process_template_file(file_path: Path, session: AsyncSession):
    """Processes a single JSON template file."""    
    print(f"Processing {file_path.name}...")
    data = json.loads(file_path.read_text(encoding="utf-8"))

    template_name = data.get("name")
    if template_name:
        template_name = template_name.replace("_", " ").capitalize()
    else:
        template_name = file_path.stem

    template_text = data["template"]
    template_variables: list[str] = data["variables"]

    id = None
    result_db = await session.execute(select(FormTemplate).where(FormTemplate.name == template_name))
    result = result_db.scalars().first()
    if result:
        if template_text.strip() != result.content.strip():
            print(f"Template '{template_name}' already exists in the database but has different content. Updating.")
            id = result.id
        else:
            print(f"Template '{template_name}' already exists in the database and has the same content. Skipping.")
            return
    else:
        print(f"Template '{template_name}' does not exist in the database. Adding.")

    summary = await generate_summary(template_text, file_path.name)
    embedding = embedding_model.encode(template_text).tolist()
    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha1(str(file_path).encode()).hexdigest()))

    qdrant_client.upsert(
        collection_name=QDRANT_COLLECTION_NAME,
        points=[
            models.PointStruct(
                id=qdrant_id,
                vector=embedding,
                payload={"name": template_name, "summary": summary, "file_name": file_path.name},
            )
        ],
        wait=True,
        ordering=models.WriteOrdering.MEDIUM,
    )
    print(f"  -> Upserted '{template_name}' to Qdrant with ID {qdrant_id}")
    
    # Create additional metadata indexes
    for field in ["name", "summary", "category"]:
        try:
            qdrant_client.create_payload_index(
                collection_name=QDRANT_COLLECTION_NAME,
                field_name=field,
                field_schema="keyword"
            )
            print(f"Created index for field: {field}")
        except Exception as e:
            print(f"Index for {field} may already exist: {e}")

    form_template_entry = FormTemplate(
        qdrant_id=qdrant_id,
        name=template_name,
        summary=summary,
        variables=template_variables,
        content=template_text,
        category=data.get("category", "other"),
    )
    if id:
        form_template_entry.id = id
    await session.merge(form_template_entry)
    print(f"  -> Added '{template_name}' to PostgreSQL.")
    await session.commit()
    print(f"  -> Committed changes to PostgreSQL.")


async def main():
    try:
        qdrant_client.get_collection(collection_name=QDRANT_COLLECTION_NAME)
        print(f"Qdrant collection '{QDRANT_COLLECTION_NAME}' already exists.")
    except Exception:
        print(f"Creating Qdrant collection '{QDRANT_COLLECTION_NAME}'...")
        embedding_size = embedding_model.get_sentence_embedding_dimension()
        qdrant_client.recreate_collection(
            collection_name=QDRANT_COLLECTION_NAME,
            vectors_config=models.VectorParams(size=embedding_size, distance=models.Distance.COSINE),
        )

    json_files = [p for p in TEMPLATES_DIR.glob("*.json") if p.is_file()]
    print(f"Found {len(json_files)} JSON template files.")

    tasks = []
    async with asyncio.TaskGroup() as tg:
        for file_path in json_files:
            tasks.append(tg.create_task(with_session(functools.partial(process_template_file, file_path))))

    print("Form template ingestion pipeline finished.")


if __name__ == "__main__":
    print(
        "NOTE: This script defines a new 'FormTemplate' table. "
        "Please create and apply a database migration using Alembic before running this script."
    )
    asyncio.run(main())
