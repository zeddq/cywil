"""
Celery tasks for embedding generation and management operations.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
import sys
import json
import os

from app.worker.celery_app import celery_app
from app.core.database_manager import DatabaseManager
from app.core.logger_manager import get_logger
from app.core.config_service import get_config

# Import embedding modules from same directory
from .embed import PolishLegalEmbedder, process_and_embed_statutes
from .sn import process_sn_ruling_file, with_session

logger = get_logger(__name__)


def run_async(coro):
    """Helper to run async code in sync context"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="embedding_tasks.generate_statute_embeddings")
def generate_statute_embeddings(code_type: str, force_regenerate: bool = False) -> Dict[str, Any]:
    """
    Generate embeddings for statute chunks.
    
    Args:
        code_type: Type of statute (KC or KPC)
        force_regenerate: Whether to force regeneration of existing embeddings
        
    Returns:
        Result dictionary with generation statistics
    """
    logger.info(f"Generating embeddings for {code_type}")
    
    try:
        # Check if chunks file exists
        chunks_file = Path("data/chunks") / f"{code_type}_chunks.json"
        if not chunks_file.exists():
            return {
                "status": "error",
                "error": f"Chunks file not found for {code_type}. Run statute ingestion first.",
                "code_type": code_type
            }
        
        # Get Qdrant configuration
        config = get_config()
        qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        
        # Process and embed statutes
        stats = process_and_embed_statutes(
            str(chunks_file),
            collection_name="statutes",
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port
        )
        
        return {
            "status": "completed",
            "code_type": code_type,
            "statistics": stats
        }
        
    except Exception as e:
        logger.error(f"Error generating statute embeddings: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "code_type": code_type
        }


@celery_app.task(name="embedding_tasks.generate_ruling_embeddings")
def generate_ruling_embeddings(jsonl_path: str) -> Dict[str, Any]:
    """
    Generate embeddings for Supreme Court rulings from JSONL file.
    
    Args:
        jsonl_path: Path to the JSONL file containing ruling data
        
    Returns:
        Result dictionary with generation statistics
    """
    logger.info(f"Generating embeddings for rulings from: {jsonl_path}")
    
    async def _process():
        db_manager = DatabaseManager()
        
        try:
            jsonl_file = Path(jsonl_path)
            if not jsonl_file.exists():
                raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")
            
            await db_manager.initialize()
            
            # Process each ruling in the JSONL file
            processed_count = 0
            error_count = 0
            
            async def process_ruling(line):
                nonlocal processed_count, error_count
                try:
                    async with db_manager.get_session() as session:
                        await process_sn_ruling_file(line, session)
                    processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing ruling: {e}")
                    error_count += 1
            
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        await process_ruling(line)
            
            return {
                "status": "completed",
                "jsonl_path": jsonl_path,
                "processed_count": processed_count,
                "error_count": error_count
            }
            
        except Exception as e:
            logger.error(f"Error generating ruling embeddings: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e),
                "jsonl_path": jsonl_path
            }
        finally:
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())


@celery_app.task(name="embedding_tasks.batch_generate_embeddings")
def batch_generate_embeddings(texts: List[str], metadata: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Generate embeddings for a batch of texts.
    
    Args:
        texts: List of texts to embed
        metadata: Optional metadata for each text
        
    Returns:
        Result dictionary with embeddings and statistics
    """
    logger.info(f"Generating embeddings for {len(texts)} texts")
    
    try:
        # Get Qdrant configuration
        qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
        qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        
        # Initialize embedder
        embedder = PolishLegalEmbedder(
            qdrant_host=qdrant_host,
            qdrant_port=qdrant_port
        )
        
        # Generate embeddings
        embeddings = embedder.generate_embeddings(texts)
        
        return {
            "status": "completed",
            "count": len(embeddings),
            "embedding_dim": embeddings.shape[1] if len(embeddings) > 0 else 0,
            "embeddings_shape": embeddings.shape
        }
        
    except Exception as e:
        logger.error(f"Error generating batch embeddings: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e),
            "text_count": len(texts)
        }


@celery_app.task(name="embedding_tasks.get_embedding_statistics")
def get_embedding_statistics(collection_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Get statistics about stored embeddings.
    
    Args:
        collection_name: Optional specific collection to get stats for
        
    Returns:
        Statistics dictionary with embedding counts and metadata
    """
    logger.info(f"Getting embedding statistics for: {collection_name or 'all collections'}")
    
    async def _process():
        try:
            from qdrant_client import AsyncQdrantClient
            
            qdrant_host = os.getenv("QDRANT_HOST", "qdrant")
            qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
            qdrant_url = f"http://{qdrant_host}:{qdrant_port}"
            
            client = AsyncQdrantClient(url=qdrant_url)
            
            if collection_name:
                # Get specific collection info
                try:
                    info = await client.get_collection(collection_name)
                    return {
                        "status": "completed",
                        "collections": {
                            collection_name: {
                                "points_count": info.points_count,
                                "vectors_count": info.vectors_count,
                                "indexed_vectors_count": info.indexed_vectors_count,
                                "status": info.status
                            }
                        }
                    }
                except Exception as e:
                    return {
                        "status": "error",
                        "error": f"Collection '{collection_name}' not found: {str(e)}"
                    }
            else:
                # Get all collections
                collections = await client.get_collections()
                stats = {}
                
                for collection in collections.collections:
                    info = await client.get_collection(collection.name)
                    stats[collection.name] = {
                        "points_count": info.points_count,
                        "vectors_count": info.vectors_count,
                        "indexed_vectors_count": info.indexed_vectors_count,
                        "status": info.status
                    }
                
                return {
                    "status": "completed",
                    "collections": stats
                }
                
        except Exception as e:
            logger.error(f"Error getting embedding statistics: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
    
    return run_async(_process())


@celery_app.task(name="embedding_tasks.optimize_embeddings")
def optimize_embeddings(collection_name: str) -> Dict[str, Any]:
    """
    Optimize embeddings in a collection (e.g., rebuild indexes).
    
    Args:
        collection_name: Name of the collection to optimize
        
    Returns:
        Result dictionary with optimization status
    """
    logger.info(f"Optimizing embeddings for collection: {collection_name}")
    
    async def _process():
        db_manager = DatabaseManager()
        service = None
        
        try:
            await db_manager.initialize()
            await service.initialize()
            
            # This would need implementation in EmbeddingService
            # For now, return a placeholder
            return {
                "status": "not_implemented",
                "message": "Optimization functionality needs to be implemented",
                "collection_name": collection_name
            }
            
        except Exception as e:
            logger.error(f"Error optimizing embeddings: {e}", exc_info=True)
            return {
                "status": "error",
                "error": str(e)
            }
        finally:
            if service:
                await service.shutdown()
            if db_manager:
                await db_manager.shutdown()
    
    return run_async(_process())
