from typing import List, Dict, Tuple, Optional
import numpy as np
from sentence_transformers import SentenceTransformer
import json
import os
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    CreateCollection, OptimizersConfigDiff,
    KeywordIndexParams, TextIndexParams
)
import logging
from tqdm import tqdm
import hashlib
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PolishLegalEmbedder:
    """Embedder optimized for Polish legal text"""
    
    def __init__(
        self,
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        qdrant_api_key: str = "paralegal"
    ):
        """
        Initialize embedder with multilingual model
        
        Args:
            model_name: SentenceTransformer model supporting Polish
            qdrant_host: Qdrant server host
            qdrant_port: Qdrant server port
        """
        self.model = SentenceTransformer(model_name)
        self.embedding_dim = self.model.get_sentence_embedding_dimension()
        self.client = QdrantClient(host=qdrant_host, port=qdrant_port, api_key=qdrant_api_key)
        
        logger.info(f"Initialized embedder with model: {model_name}")
        logger.info(f"Embedding dimension: {self.embedding_dim}")
    
    def create_collection(self, collection_name: str = "statutes"):
        """Create Qdrant collection for statute embeddings"""
        try:
            # Check if collection exists
            collections = self.client.get_collections().collections
            if any(c.name == collection_name for c in collections):
                logger.info(f"Collection '{collection_name}' already exists")
                return
            
            # Create collection
            if self.embedding_dim is None:
                raise ValueError("Unable to determine embedding dimension")
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_dim,
                    distance=Distance.COSINE
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=20000,
                    memmap_threshold=50000
                )
            )
            
            # Create payload indexes for efficient filtering
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name="code",
                field_schema=KeywordIndexParams()
            )
            
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name="article",
                field_schema=KeywordIndexParams()
            )
            
            self.client.create_payload_index(
                collection_name=collection_name,
                field_name="status",
                field_schema=KeywordIndexParams()
            )
            
            logger.info(f"Created collection '{collection_name}' with indexes")
            
        except Exception as e:
            logger.error(f"Error creating collection: {e}")
            raise
    
    def generate_embeddings(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """
        Generate embeddings for texts with batching
        
        Args:
            texts: List of text strings
            batch_size: Batch size for encoding
            
        Returns:
            Numpy array of embeddings
        """
        embeddings = self.model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=True,  # Cosine similarity
            show_progress_bar=True,
            batch_size=batch_size,
        )
        
        return embeddings
    
    def prepare_statute_texts(self, chunks: List[Dict]) -> List[str]:
        """
        Prepare texts for embedding with legal context
        
        Args:
            chunks: List of chunk dictionaries
            
        Returns:
            List of prepared text strings
        """
        prepared_texts = []
        
        for chunk in chunks:
            # Build context-rich text
            text_parts = []
            
            # Add article reference
            metadata = chunk.get("metadata", {})
            article = metadata.get("article", "")
            code = metadata.get("code", "")
            
            if article and code:
                text_parts.append(f"Art. {article} {code}")
            
            # Add title if present
            if metadata.get("title"):
                text_parts.append(f"[{metadata['title']}]")
            
            # Add section/chapter context
            if metadata.get("section"):
                text_parts.append(f"({metadata['section']})")
            
            # Add main content
            text_parts.append(chunk["text"])
            
            # Combine with proper spacing
            prepared_text = " ".join(text_parts)
            prepared_texts.append(prepared_text)
        
        return prepared_texts
    
    def upload_to_qdrant(
        self,
        chunks: List[Dict],
        embeddings: np.ndarray,
        collection_name: str = "statutes",
        batch_size: int = 100
    ):
        """
        Upload embeddings and metadata to Qdrant
        
        Args:
            chunks: List of chunk dictionaries
            embeddings: Numpy array of embeddings
            collection_name: Name of Qdrant collection
            batch_size: Batch size for upload
        """
        points = []
        
        for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
            # Generate unique ID
            chunk_id: str = chunk.get("chunk_id", f"chunk_{i}")
            # Use hash as integer to avoid UUID format issues
            point_id = int(hashlib.md5(chunk_id.encode()).hexdigest()[:8], base=16)
            
            # Prepare payload
            payload = {
                "chunk_id": chunk_id,
                "text": chunk["text"],
                **chunk.get("metadata", {})
            }
            
            # Create point
            point = PointStruct(
                id=point_id,
                vector=embedding.tolist(),
                payload=payload
            )
            points.append(point)
            
            # Upload in batches
            if len(points) >= batch_size:
                self.client.upsert(
                    collection_name=collection_name,
                    points=points,
                )
                logger.info(f"Uploaded batch of {len(points)} points")
                points = []
        
        # Upload remaining points
        if points:
            self.client.upsert(
                collection_name=collection_name,
                points=points
            )
            logger.info(f"Uploaded final batch of {len(points)} points")
        
        # Get collection info
        info = self.client.get_collection(collection_name)
        logger.info(f"Collection '{collection_name}' now has {info.points_count} points")

def process_and_embed_statutes(
    chunks_file: str,
    collection_name: str = "statutes",
    qdrant_host: str = "qdrant",
    qdrant_port: int = 6333,
    qdrant_api_key: str = "paralegal"
) -> Dict:
    """
    Complete pipeline to embed statute chunks
    
    Args:
        chunks_file: Path to JSON file with chunks
        collection_name: Qdrant collection name
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
        
    Returns:
        Dictionary with processing statistics
    """
    # Load chunks
    logger.info(f"Loading chunks from {chunks_file}")
    with open(chunks_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    chunks = data["chunks"]
    code_type = data["code"]
    
    logger.info(f"Loaded {len(chunks)} chunks for {code_type}")
    
    # Initialize embedder
    logger.info(f"Initializing embedder with host: {qdrant_host} and port: {qdrant_port}")
    embedder = PolishLegalEmbedder(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        qdrant_api_key=qdrant_api_key
    )
    
    # Create collection
    embedder.create_collection(collection_name)
    
    # Prepare texts
    texts = embedder.prepare_statute_texts(chunks)
    
    # Generate embeddings
    logger.info("Generating embeddings...")
    embeddings = embedder.generate_embeddings(texts)
    
    # Upload to Qdrant
    logger.info("Uploading to Qdrant...")
    embedder.upload_to_qdrant(chunks, embeddings, collection_name)
    
    # Save embeddings locally as backup
    output_dir = Path(chunks_file).parent
    embeddings_file = output_dir / f"{code_type}_embeddings.npy"
    np.save(embeddings_file, embeddings)
    logger.info(f"Saved embeddings to {embeddings_file}")
    
    # Return statistics
    stats = {
        "code": code_type,
        "chunks_processed": len(chunks),
        "embeddings_generated": embeddings.shape[0],
        "embedding_dimension": embeddings.shape[1],
        "collection_name": collection_name,
        "processing_date": datetime.now().isoformat()
    }
    
    return stats

def create_hybrid_search_index(
    collection_name: str = "statutes",
    qdrant_host: str = "localhost",
    qdrant_api_key: str = "paralegal",
    qdrant_port: int = 6333
):
    """
    Create additional indexes for hybrid search
    
    Args:
        collection_name: Qdrant collection name
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
    """
    client = QdrantClient(host=qdrant_host, port=qdrant_port, api_key=qdrant_api_key)
    
    # Create text search index
    try:
        client.create_payload_index(
            collection_name=collection_name,
            field_name="text",
            field_schema=TextIndexParams()
        )
        logger.info("Created text search index")
    except Exception as e:
        logger.warning(f"Text index may already exist: {e}")
    
    # Create additional metadata indexes
    for field in ["book", "chapter", "paragraph"]:
        try:
            client.create_payload_index(
                collection_name=collection_name,
                field_name=field,
                field_schema=KeywordIndexParams()
            )
            logger.info(f"Created index for field: {field}")
        except Exception as e:
            logger.warning(f"Index for {field} may already exist: {e}")

def search_statutes(
    query: str,
    code_filter: Optional[str] = None,
    collection_name: str = "statutes",
    qdrant_host: str = "localhost",
    qdrant_port: int = 6333,
    qdrant_api_key: str = "paralegal",
    top_k: int = 5
) -> List[Dict]:
    """
    Search statutes using vector similarity
    
    Args:
        query: Search query
        code_filter: Filter by code (KC or KPC)
        collection_name: Qdrant collection name
        qdrant_host: Qdrant server host
        qdrant_port: Qdrant server port
        top_k: Number of results
        
    Returns:
        List of search results
    """
    # Initialize embedder
    embedder = PolishLegalEmbedder(
        qdrant_host=qdrant_host,
        qdrant_port=qdrant_port,
        qdrant_api_key=qdrant_api_key
    )
    
    # Generate query embedding
    query_embedding = embedder.model.encode(query, normalize_embeddings=True)
    
    # Build filter
    search_filter = None
    if code_filter:
        search_filter = Filter(
            must=[
                FieldCondition(
                    key="code",
                    match=MatchValue(value=code_filter)
                )
            ]
        )
    
    # Search
    results = embedder.client.search(
        collection_name=collection_name,
        query_vector=query_embedding.tolist(),
        query_filter=search_filter,
        limit=top_k,
        with_payload=True
    )
    
    # Format results
    formatted_results = []
    for result in results:
        if result.payload is None:
            continue        formatted_results.append({
            "score": result.score,
            "article": result.payload.get("article"),
            "code": result.payload.get("code"),
            "text": result.payload.get("text"),
            "title": result.payload.get("title"),
            "metadata": result.payload
        })
    
    return formatted_results

if __name__ == "__main__":
    # Process KC chunks
    kc_stats = process_and_embed_statutes(
        "data/chunks/KC_chunks.json",
        collection_name="statutes"
    )
    print(f"KC embedding stats: {kc_stats}")
    
    # Process KPC chunks
    kpc_stats = process_and_embed_statutes(
        "data/chunks/KPC_chunks.json",
        collection_name="statutes"
    )
    print(f"KPC embedding stats: {kpc_stats}")
    
    # Create hybrid search indexes
    create_hybrid_search_index()
    
    # Test search
    results = search_statutes(
        "odpowiedzialność kontraktowa",
        code_filter="KC",
        top_k=3
    )
    
    print("\nSearch results:")
    for i, result in enumerate(results):
        print(f"\n{i+1}. Art. {result['article']} {result['code']} (score: {result['score']:.3f})")
        print(f"   {result['text'][:200]}...")
