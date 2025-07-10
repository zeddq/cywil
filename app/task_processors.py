import asyncio
import hashlib
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from .database import get_db
from .models import Document
from datetime import datetime
import aiofiles
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance, 
    VectorParams, 
    PointStruct,
    CollectionInfo,
    Filter,
    FieldCondition,
    MatchValue
)
from sentence_transformers import SentenceTransformer
import uuid
from .config import settings
import fitz
logger = logging.getLogger(__name__)


class DocumentProcessor:
    """Background task processor for document processing"""
    
    def __init__(self, queue: asyncio.Queue):
        self.queue = queue
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        self.qdrant_client: Optional[QdrantClient] = None
        self.embedder: Optional[SentenceTransformer] = None
        self.chunk_size = 1000  # Characters per chunk
        self.chunk_overlap = 200  # Overlap between chunks
    
    async def start(self):
        """Start the document processor background task"""
        if self.is_running:
            logger.warning("Document processor is already running")
            return
        
        # Initialize Qdrant client and embedder
        await self._initialize_clients()
        
        self.is_running = True
        self.task = asyncio.create_task(self._process_documents())
        logger.info("Document processor started")
    
    async def _initialize_clients(self):
        """Initialize Qdrant client and sentence transformer"""
        try:
            # Initialize Qdrant client
            self.qdrant_client = QdrantClient(
                host=settings.qdrant_host,
                port=settings.qdrant_port
            )
            logger.info(f"Connected to Qdrant at {settings.qdrant_host}:{settings.qdrant_port}")
            
            # Initialize sentence transformer
            logger.info("Loading sentence transformer model...")
            self.embedder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
            logger.info("Sentence transformer loaded successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize clients: {e}")
            raise
    
    async def stop(self):
        """Stop the document processor"""
        self.is_running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        logger.info("Document processor stopped")

    async def put(self, document_id: str):
        """Add a document ID to the processing queue"""
        await self.queue.put(document_id)
    
    async def _process_documents(self):
        """Main processing loop"""
        logger.info("Document processing worker started")
        
        while self.is_running:
            try:
                # Wait for document ID from queue (timeout after 1 second to check is_running)
                try:
                    document_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
                # Process the document
                await self._process_single_document(document_id)
                
            except Exception as e:
                logger.error(f"Error in document processing loop: {e}", exc_info=True)
                # Continue processing even if one document fails
    
    async def _ensure_collection_exists(self, case_id: str) -> str:
        """Ensure Qdrant collection exists for the case"""
        collection_name = f"case_{case_id}_documents"
        
        try:
            # Check if collection exists
            collections = self.qdrant_client.get_collections()
            exists = any(col.name == collection_name for col in collections.collections)
            
            if not exists:
                # Create collection with vector size matching the embedder
                vector_size = self.embedder.get_sentence_embedding_dimension()
                self.qdrant_client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE)
                )
                logger.info(f"Created new collection: {collection_name}")
            else:
                logger.info(f"Collection already exists: {collection_name}")
                
            return collection_name
            
        except Exception as e:
            logger.error(f"Error managing collection {collection_name}: {e}")
            raise
    
    def _chunk_text(self, text: str) -> List[Dict[str, Any]]:
        """Chunk text by paragraphs (delimited by double newlines)"""
        chunks = []
        text_length = len(text)
        
        # Split by double newlines to get paragraphs
        paragraphs = text.split("\n\n")
        
        chunk_num = 0
        current_position = 0
        
        for paragraph in paragraphs:
            # Skip empty paragraphs
            paragraph = paragraph.strip()
            if not paragraph:
                continue
            
            # Find the actual position of this paragraph in the original text
            start_char = text.find(paragraph, current_position)
            end_char = start_char + len(paragraph) if start_char != -1 else current_position + len(paragraph)
            
            # Store chunk with metadata
            chunks.append({
                "text": paragraph,
                "chunk_num": chunk_num,
                "start_char": start_char if start_char != -1 else current_position,
                "end_char": end_char
            })
            
            # Update position for next search
            if start_char != -1:
                current_position = end_char
            
            chunk_num += 1
        
        # If no paragraphs were found (text doesn't contain double newlines),
        # fall back to treating the whole text as one chunk
        if not chunks and text.strip():
            chunks.append({
                "text": text.strip(),
                "chunk_num": 0,
                "start_char": 0,
                "end_char": len(text)
            })
            
        logger.info(f"Created {len(chunks)} paragraph chunks from text of length {text_length}")
        return chunks
    
    async def _read_document_content(self, file_path: str) -> str:
        """Read document content from file"""
        try:
            if file_path.endswith(".txt"):
                async with aiofiles.open(file_path, 'r', encoding='utf-8') as f:
                    content = await f.read()
                return content
            elif file_path.endswith(".pdf"):
                async with aiofiles.open(file_path, 'rb') as f:
                    fitz_doc = fitz.open(stream=f, filetype="pdf")
                    content = ""
                    for page in fitz_doc:
                        content += page.get_text()
                return content
            else:
                raise ValueError(f"Unsupported file type: {file_path}")
        except UnicodeDecodeError:
            # Try with different encoding
            async with aiofiles.open(file_path, 'r', encoding='latin-1') as f:
                content = await f.read()
            return content
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            raise
    
    async def _process_single_document(self, document_id: str):
        """Process a single document"""
        logger.info(f"Processing document: {document_id}")
        
        try:
            # Get database session
            async for db in get_db():
                # Fetch document from database
                document = await db.get(Document, document_id)
                if not document:
                    logger.error(f"Document {document_id} not found in database")
                    return
                
                # Log document info
                logger.info(f"Processing document: {document.title} (ID: {document.id})")
                logger.info(f"Document type: {document.document_type}")
                logger.info(f"File path: {document.file_path}")
                logger.info(f"Case ID: {document.case_id}")
                
                # Ensure collection exists
                collection_name = await self._ensure_collection_exists(document.case_id)
                
                # Read document content
                content = await self._read_document_content(document.file_path)
                
                # Chunk the document
                chunks = self._chunk_text(content)
                
                # Process chunks and create embeddings
                points = []
                for i, chunk in enumerate(chunks):
                    # Generate embedding
                    embedding = self.embedder.encode(chunk["text"]).tolist()
                    qdrant_id = str(uuid.uuid5(uuid.NAMESPACE_URL, hashlib.sha1(str(document.file_path).encode()).hexdigest()))

                    # Create point for Qdrant
                    point = PointStruct(
                        id=qdrant_id,
                        vector=embedding,
                        payload={
                            "document_id": document_id,
                            "document_title": document.title,
                            "case_id": document.case_id,
                            "chunk_num": chunk["chunk_num"],
                            "text": chunk["text"],
                            "start_char": chunk["start_char"],
                            "end_char": chunk["end_char"],
                            "file_path": document.file_path,
                            "created_at": datetime.now().isoformat()
                        }
                    )
                    points.append(point)
                
                # Upload points to Qdrant in batches
                batch_size = 100
                for i in range(0, len(points), batch_size):
                    batch = points[i:i + batch_size]
                    self.qdrant_client.upsert(
                        collection_name=collection_name,
                        points=batch
                    )
                    logger.info(f"Uploaded batch {i//batch_size + 1} of {len(points)//batch_size + 1}")
                
                # Update document metadata to indicate processing
                if not document.metadata:
                    document.metadata = {}
                
                document.metadata.update({
                    "processed": True,
                    "processed_at": datetime.now().isoformat(),
                    "processing_status": "completed",
                    "chunks_created": len(chunks),
                    "collection_name": collection_name
                })
                
                # Save updates
                db.add(document)
                await db.commit()
                
                logger.info(f"Successfully processed document: {document_id} with {len(chunks)} chunks")
                
        except Exception as e:
            logger.error(f"Error processing document {document_id}: {e}", exc_info=True)
            
            # Try to update document status to failed
            try:
                async for db in get_db():
                    document = await db.get(Document, document_id)
                    if document:
                        if not document.metadata:
                            document.metadata = {}
                        document.metadata.update({
                            "processed": False,
                            "processed_at": datetime.now().isoformat(),
                            "processing_status": "failed",
                            "processing_error": str(e)
                        })
                        db.add(document)
                        await db.commit()
            except Exception as update_error:
                logger.error(f"Failed to update document status: {update_error}")


# Global document processor instance
document_processor: Optional[DocumentProcessor] = None


def get_document_processor(queue: asyncio.Queue) -> DocumentProcessor:
    """Get or create the document processor instance"""
    global document_processor
    if document_processor is None:
        document_processor = DocumentProcessor(queue)
    return document_processor
