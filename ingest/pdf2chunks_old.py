import re
from typing import List, Dict, Tuple, Optional
import pdfplumber
from pathlib import Path
import json
from dataclasses import dataclass
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ArticleChunk:
    """Represents a single article or section from the legal code"""
    code: str  # KC or KPC
    article_num: str  # e.g., "415", "415¹", "415§2"
    title: Optional[str]  # Article title if present
    content: str  # Full text of the article
    section: Optional[str]  # Section/Book this article belongs to
    metadata: Dict  # Additional metadata

class PolishStatuteParser:
    """Parser specifically designed for Polish legal statutes"""
    
    # Regex patterns for Polish legal structure
    PATTERNS = {
        # Main article pattern: "Art. 123." or "Art. 123¹." or "Art. 123^2."
        'article': re.compile(r'^Art\.\s*(\d+[¹²³⁴⁵⁶⁷⁸⁹]*)\s*\.', re.MULTILINE),
        
        # Section/paragraph pattern: "§ 1." or "§ 2."
        'paragraph': re.compile(r'^§\s*(\d+)\s*\.', re.MULTILINE),
        
        # Point pattern: "1)" or "2)" at start of line
        'point': re.compile(r'^(\d+)\)', re.MULTILINE),
        
        # Book/Title pattern: "KSIĘGA PIERWSZA" or "TYTUŁ I"
        'book': re.compile(r'^(KSIĘGA\s+\w+|TYTUŁ\s+[IVXLCDM]+)', re.MULTILINE),
        
        # Chapter pattern: "Rozdział I" or "DZIAŁ I"
        'chapter': re.compile(r'^(Rozdział\s+[IVXLCDM]+|DZIAŁ\s+[IVXLCDM]+)', re.MULTILINE),
        
        # Deleted article pattern: "(uchylony)" or "(skreślony)"
        'deleted': re.compile(r'\(uchylon[ya]\)|\(skreślon[ya]\)')
    }
    
    def __init__(self, code_type: str = "KC"):
        """
        Initialize parser for specific code type
        
        Args:
            code_type: Type of code (KC or KPC)
        """
        self.code_type = code_type
        self.current_section = None
        self.current_book = None
        self.current_chapter = None
    
    def parse_pdf(self, pdf_path: str) -> List[ArticleChunk]:
        """
        Parse PDF and extract structured articles
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of ArticleChunk objects
        """
        chunks = []
        
        with pdfplumber.open(pdf_path) as pdf:
            full_text = ""
            
            # Extract text from all pages
            for page_num, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
                    logger.info(f"Processed page {page_num + 1}/{len(pdf.pages)}")
            
            # Parse the complete text
            chunks = self._parse_text(full_text)
            
        logger.info(f"Extracted {len(chunks)} articles from {pdf_path}")
        return chunks
    
    def _parse_text(self, text: str) -> List[ArticleChunk]:
        """Parse the complete text and extract articles"""
        chunks = []
        
        # Split by articles
        article_splits = self.PATTERNS['article'].split(text)
        
        # Process introduction/preamble if exists
        if article_splits[0].strip():
            preamble = article_splits[0].strip()
            if len(preamble) > 100:  # Only if substantial
                chunks.append(ArticleChunk(
                    code=self.code_type,
                    article_num="Preambuła",
                    title="Preambuła",
                    content=preamble,
                    section=None,
                    metadata={"type": "preamble"}
                ))
        
        # Process each article
        i = 1
        while i < len(article_splits) - 1:
            article_num = article_splits[i]
            article_content = article_splits[i + 1]
            
            # Find the end of this article (start of next article or end of text)
            next_article_match = self.PATTERNS['article'].search(article_content)
            if next_article_match:
                article_text = article_content[:next_article_match.start()]
                remaining_text = article_content[next_article_match.start():]
                article_splits[i + 1] = remaining_text
            else:
                article_text = article_content
            
            # Update current section/chapter if found
            self._update_structure_context(article_text)
            
            # Check if article is deleted
            if self.PATTERNS['deleted'].search(article_text[:100]):
                metadata = {"status": "deleted", "type": "article"}
            else:
                metadata = {"status": "active", "type": "article"}
            
            # Parse paragraphs within the article
            paragraphs = self._parse_paragraphs(article_text)
            
            if paragraphs:
                # Create separate chunks for each paragraph
                for para_num, para_content in paragraphs.items():
                    chunk_id = f"{article_num}§{para_num}" if para_num != "main" else article_num
                    chunks.append(ArticleChunk(
                        code=self.code_type,
                        article_num=chunk_id,
                        title=self._extract_article_title(article_text),
                        content=para_content,
                        section=self.current_section,
                        metadata={
                            **metadata,
                            "paragraph": para_num,
                            "book": self.current_book,
                            "chapter": self.current_chapter
                        }
                    ))
            else:
                # Single chunk for the entire article
                chunks.append(ArticleChunk(
                    code=self.code_type,
                    article_num=article_num,
                    title=self._extract_article_title(article_text),
                    content=article_text.strip(),
                    section=self.current_section,
                    metadata={
                        **metadata,
                        "book": self.current_book,
                        "chapter": self.current_chapter
                    }
                ))
            
            i += 2
        
        return chunks
    
    def _parse_paragraphs(self, article_text: str) -> Dict[str, str]:
        """Parse paragraphs (§) within an article"""
        paragraphs = {}
        
        para_splits = self.PATTERNS['paragraph'].split(article_text)
        
        if len(para_splits) > 1:
            # Has explicit paragraphs
            # First part before any § is the main content
            if para_splits[0].strip():
                paragraphs["main"] = para_splits[0].strip()
            
            # Process each paragraph
            i = 1
            while i < len(para_splits) - 1:
                para_num = para_splits[i]
                para_content = para_splits[i + 1]
                
                # Find end of this paragraph
                next_para_match = self.PATTERNS['paragraph'].search(para_content)
                if next_para_match:
                    para_text = para_content[:next_para_match.start()]
                else:
                    para_text = para_content
                
                paragraphs[para_num] = para_text.strip()
                i += 2
        else:
            # No paragraphs, treat as single content
            if article_text.strip():
                paragraphs["main"] = article_text.strip()
        
        return paragraphs
    
    def _update_structure_context(self, text: str):
        """Update current book/chapter/section based on text"""
        # Check for book
        book_match = self.PATTERNS['book'].search(text)
        if book_match:
            self.current_book = book_match.group(1)
        
        # Check for chapter
        chapter_match = self.PATTERNS['chapter'].search(text)
        if chapter_match:
            self.current_chapter = chapter_match.group(1)
            self.current_section = chapter_match.group(1)
    
    def _extract_article_title(self, text: str) -> Optional[str]:
        """Extract article title if present (usually in square brackets)"""
        title_match = re.search(r'\[([^\]]+)\]', text[:200])
        if title_match:
            return title_match.group(1)
        return None

class StatuteChunker:
    """Intelligent chunking for legal documents"""
    
    def __init__(self, max_chunk_size: int = 1000, overlap: int = 200):
        """
        Initialize chunker
        
        Args:
            max_chunk_size: Maximum characters per chunk
            overlap: Number of overlapping characters between chunks
        """
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
    
    def chunk_articles(self, articles: List[ArticleChunk]) -> List[Dict]:
        """
        Convert articles to chunks suitable for embedding
        
        Args:
            articles: List of parsed articles
            
        Returns:
            List of chunk dictionaries
        """
        chunks = []
        
        for article in articles:
            # If article is small enough, keep as single chunk
            if len(article.content) <= self.max_chunk_size:
                chunks.append(self._article_to_chunk(article))
            else:
                # Split large articles intelligently
                sub_chunks = self._split_large_article(article)
                chunks.extend(sub_chunks)
        
        return chunks
    
    def _article_to_chunk(self, article: ArticleChunk, sub_index: int = 0) -> Dict:
        """Convert ArticleChunk to chunk dictionary"""
        chunk_id = f"{article.code}_art_{article.article_num}"
        if sub_index > 0:
            chunk_id += f"_part{sub_index}"
        
        return {
            "chunk_id": chunk_id,
            "text": article.content,
            "metadata": {
                "code": article.code,
                "article": article.article_num,
                "title": article.title,
                "section": article.section,
                **article.metadata,
                "chunk_index": sub_index,
                "indexing_date": datetime.now().isoformat()
            }
        }
    
    def _split_large_article(self, article: ArticleChunk) -> List[Dict]:
        """Split large article into smaller chunks"""
        chunks = []
        text = article.content
        
        # Try to split by points first
        point_splits = re.split(r'(\n\d+\))', text)
        
        current_chunk = ""
        chunk_index = 1
        
        for i, part in enumerate(point_splits):
            if i % 2 == 0:  # Content part
                if len(current_chunk) + len(part) > self.max_chunk_size and current_chunk:
                    # Save current chunk
                    chunk_article = ArticleChunk(
                        code=article.code,
                        article_num=article.article_num,
                        title=article.title,
                        content=current_chunk.strip(),
                        section=article.section,
                        metadata={**article.metadata, "partial": True}
                    )
                    chunks.append(self._article_to_chunk(chunk_article, chunk_index))
                    chunk_index += 1
                    
                    # Start new chunk with overlap
                    overlap_start = max(0, len(current_chunk) - self.overlap)
                    current_chunk = current_chunk[overlap_start:] + part
                else:
                    current_chunk += part
            else:  # Point number
                current_chunk += part
        
        # Add final chunk
        if current_chunk.strip():
            chunk_article = ArticleChunk(
                code=article.code,
                article_num=article.article_num,
                title=article.title,
                content=current_chunk.strip(),
                section=article.section,
                metadata={**article.metadata, "partial": True}
            )
            chunks.append(self._article_to_chunk(chunk_article, chunk_index))
        
        return chunks

def process_statute_pdf(
    pdf_path: str,
    code_type: str,
    output_dir: str = "data/chunks"
) -> Tuple[List[Dict], Dict]:
    """
    Complete pipeline to process a statute PDF
    
    Args:
        pdf_path: Path to PDF file
        code_type: Type of code (KC or KPC)
        output_dir: Directory to save chunks
        
    Returns:
        Tuple of (chunks, statistics)
    """
    # Create output directory
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    
    # Parse PDF
    parser = PolishStatuteParser(code_type)
    articles = parser.parse_pdf(pdf_path)
    
    # Chunk articles
    chunker = StatuteChunker()
    chunks = chunker.chunk_articles(articles)
    
    # Generate statistics
    stats = {
        "total_articles": len(articles),
        "total_chunks": len(chunks),
        "deleted_articles": sum(1 for a in articles if a.metadata.get("status") == "deleted"),
        "articles_with_paragraphs": sum(1 for a in articles if "paragraph" in a.metadata),
        "average_chunk_size": sum(len(c["text"]) for c in chunks) / len(chunks) if chunks else 0
    }
    
    # Save chunks
    output_file = Path(output_dir) / f"{code_type}_chunks.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "code": code_type,
            "chunks": chunks,
            "statistics": stats,
            "processing_date": datetime.now().isoformat()
        }, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved {len(chunks)} chunks to {output_file}")
    logger.info(f"Statistics: {stats}")
    
    return chunks, stats

if __name__ == "__main__":
    # Example usage
    kc_chunks, kc_stats = process_statute_pdf(
        "data/kodeks_cywilny.pdf",
        "KC"
    )
    
    kpc_chunks, kpc_stats = process_statute_pdf(
        "data/kodeks_postepowania_cywilnego.pdf", 
        "KPC"
    )