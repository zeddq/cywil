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
    article: str  # e.g., "415", "415¹", "415§2"
    title: Optional[str]  # Article title if present
    content: str  # Full text of the article
    section: Optional[str]  # Section/Book this article belongs to
    metadata: Dict  # Additional metadata

class PolishStatuteParser:
    """Parser specifically designed for Polish legal statutes with correct hierarchy"""
    
    # Polish legal document hierarchy:
    # 1. Część (Part) - highest level
    # 2. Dział (Division)
    # 3. Rozdział (Chapter)
    # 4. Artykuł (Article) - lowest level
    
    # Regex patterns for Polish legal structure
    PATTERNS = {
        # Main article pattern: "Art. 123." or "Art. 123¹." or "Art. 123^2."
        'article': re.compile(r'^Art\.\s*(\d+[¹²³⁴⁵⁶⁷⁸⁹]*)\s*\.', re.MULTILINE),
        
        # Section/paragraph pattern within articles: "§ 1." or "§ 2."
        'paragraph': re.compile(r'^§\s*(\d+)\s*\.', re.MULTILINE),
        
        # Point pattern: "1)" or "2)" at start of line
        'point': re.compile(r'^(\d+)\)', re.MULTILINE),
        
        # Part pattern: "CZĘŚĆ OGÓLNA", "CZĘŚĆ SZCZEGÓLNA", "CZĘŚĆ PIERWSZA", etc.
        'part': re.compile(r'^CZĘŚĆ\s+(\w+)', re.MULTILINE),
        
        # Division pattern: "DZIAŁ I", "DZIAŁ II", etc.
        'division': re.compile(r'^DZIAŁ\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
        
        # Chapter pattern: "Rozdział I", "Rozdział II", etc.
        'chapter': re.compile(r'^Rozdział\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
        
        # Book pattern (some codes have this): "KSIĘGA PIERWSZA" etc.
        'book': re.compile(r'^KSIĘGA\s+(\w+)', re.MULTILINE),
        
        # Title pattern (alternative structure): "TYTUŁ I"
        'title': re.compile(r'^TYTUŁ\s+([IVXLCDM]+)(?:\s|$)', re.MULTILINE),
        
        # Deleted article pattern: "(uchylony)" or "(skreślony)"
        'deleted': re.compile(r'\(uchylon[ya]\)|\(skreślon[ya]\)'),
        
        # Section headers with names (match on same line only)
        'named_part': re.compile(r'^CZĘŚĆ\s+(\w+)(?:\s*[:\-\s]+(.+?))?$', re.MULTILINE),
        'named_division': re.compile(r'^DZIAŁ\s+([IVXLCDM]+)(?:\s*[:\-\s]+(.+?))?$', re.MULTILINE),
        'named_chapter': re.compile(r'^Rozdział\s+([IVXLCDM]+)(?:\s*[:\-\s]+(.+?))?$', re.MULTILINE),
    }
    
    def __init__(self, code_type: str = "KC"):
        """
        Initialize parser for specific code type
        
        Args:
            code_type: Type of code (KC or KPC)
        """
        self.code_type = code_type
        self.current_part = None
        self.current_part_name = None
        self.current_division = None
        self.current_division_name = None
        self.current_chapter = None
        self.current_chapter_name = None
        self.current_book = None  # Some codes use books
        self.current_title = None  # Alternative to chapters
    
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
            # Update structure context from preamble
            self._update_structure_context(preamble)
            
            if len(preamble) > 100:  # Only if substantial
                chunks.append(ArticleChunk(
                    code=self.code_type,
                    article="Preambuła",
                    title="Preambuła",
                    content=preamble,
                    section=self._get_current_section_path(),
                    metadata={
                        "type": "preamble",
                        "hierarchy": self._get_hierarchy_metadata()
                    }
                ))
        
        # Process each article
        i = 1
        while i < len(article_splits) - 1:
            article = article_splits[i]
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
            
            # Add hierarchy information
            metadata.update({"hierarchy": self._get_hierarchy_metadata()})
            
            # Parse paragraphs within the article
            paragraphs = self._parse_paragraphs(article_text)
            
            if paragraphs:
                # Create separate chunks for each paragraph
                for para_num, para_content in paragraphs.items():
                    chunk_id = f"{article}§{para_num}" if para_num != "main" else article
                    chunks.append(ArticleChunk(
                        code=self.code_type,
                        article=chunk_id,
                        title=self._extract_article_title(article_text),
                        content=para_content,
                        section=self._get_current_section_path(),
                        metadata={
                            **metadata,
                            "paragraph": para_num
                        }
                    ))
            else:
                # Single chunk for the entire article
                chunks.append(ArticleChunk(
                    code=self.code_type,
                    article=article,
                    title=self._extract_article_title(article_text),
                    content=article_text.strip(),
                    section=self._get_current_section_path(),
                    metadata=metadata
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
        """Update current hierarchy based on text"""
        
        # Split text into lines for more accurate parsing
        lines = text.split('\n')
        
        for i, line in enumerate(lines):
            line = line.strip()
            
            # Check for part (highest level)
            if line.startswith('CZĘŚĆ'):
                part_match = self.PATTERNS['part'].match(line)
                if part_match:
                    self.current_part = part_match.group(1)
                    # Look for part name on the same or next line
                    self.current_part_name = None
                    # Only check same line after colon or dash
                    if ':' in line:
                        self.current_part_name = line.split(':', 1)[1].strip()
                    elif '-' in line:
                        self.current_part_name = line.split('-', 1)[1].strip()
                    # Reset lower levels when entering new part
                    self.current_division = None
                    self.current_division_name = None
                    self.current_chapter = None
                    self.current_chapter_name = None
            
            # Check for division (second level)
            elif line.startswith('DZIAŁ'):
                division_match = self.PATTERNS['division'].match(line)
                if division_match:
                    self.current_division = division_match.group(1)
                    self.current_division_name = None
                    # Reset lower levels
                    self.current_chapter = None
                    self.current_chapter_name = None
                    # Check if there's a name on the next line
                    if i + 1 < len(lines) and not any(pattern in lines[i + 1] for pattern in ['Art.', 'CZĘŚĆ', 'DZIAŁ', 'Rozdział', 'KSIĘGA', 'TYTUŁ']):
                        next_line = lines[i + 1].strip()
                        if next_line and not next_line[0].isdigit():
                            self.current_division_name = next_line
            
            # Check for chapter (third level)
            elif line.startswith('Rozdział'):
                chapter_match = self.PATTERNS['chapter'].match(line)
                if chapter_match:
                    self.current_chapter = chapter_match.group(1)
                    self.current_chapter_name = None
                    # Check if there's a name on the next line
                    if i + 1 < len(lines) and not any(pattern in lines[i + 1] for pattern in ['Art.', 'CZĘŚĆ', 'DZIAŁ', 'Rozdział', 'KSIĘGA', 'TYTUŁ']):
                        next_line = lines[i + 1].strip()
                        if next_line and not next_line[0].isdigit():
                            self.current_chapter_name = next_line
            
            # Check for book (alternative structure, used between Part and Division)
            elif line.startswith('KSIĘGA'):
                book_match = self.PATTERNS['book'].match(line)
                if book_match:
                    self.current_book = book_match.group(1)
                    # Reset lower levels
                    self.current_division = None
                    self.current_division_name = None
                    self.current_chapter = None
                    self.current_chapter_name = None
            
            # Check for title (alternative to chapter)
            elif line.startswith('TYTUŁ'):
                title_match = self.PATTERNS['title'].match(line)
                if title_match:
                    self.current_title = title_match.group(1)
    
    def _get_current_section_path(self) -> str:
        """Get the current section path as a string"""
        path_parts = []
        
        if self.current_part:
            part_str = f"Część {self.current_part}"
            if self.current_part_name:
                part_str += f": {self.current_part_name}"
            path_parts.append(part_str)
        
        if self.current_division:
            div_str = f"Dział {self.current_division}"
            if self.current_division_name:
                div_str += f": {self.current_division_name}"
            path_parts.append(div_str)
        
        if self.current_chapter:
            chap_str = f"Rozdział {self.current_chapter}"
            if self.current_chapter_name:
                chap_str += f": {self.current_chapter_name}"
            path_parts.append(chap_str)
        
        return " > ".join(path_parts) if path_parts else None
    
    def _get_hierarchy_metadata(self) -> Dict:
        """Get current hierarchy as metadata dictionary"""
        return {
            "part": self.current_part,
            "part_name": self.current_part_name,
            "division": self.current_division,
            "division_name": self.current_division_name,
            "chapter": self.current_chapter,
            "chapter_name": self.current_chapter_name,
            "book": self.current_book,
            "title": self.current_title
        }
    
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
            # Create chunk ID with hierarchy information
            chunk_base_id = f"{article.code}_art_{article.article}"
            
            # Include hierarchy in chunk for better search
            hierarchy_text = ""
            if article.section:
                hierarchy_text = f"[{article.section}]\n"
            
            # For small articles, keep as single chunk
            if len(article.content) <= self.max_chunk_size:
                chunks.append({
                    "chunk_id": chunk_base_id,
                    "text": hierarchy_text + article.content,
                    "metadata": {
                        "code": article.code,
                        "article": article.article,
                        "title": article.title,
                        "section": article.section,
                        **article.metadata
                    }
                })
            else:
                # Split large articles intelligently
                sub_chunks = self._split_article(article.content)
                
                for i, sub_chunk in enumerate(sub_chunks):
                    chunks.append({
                        "chunk_id": f"{chunk_base_id}_part{i+1}",
                        "text": hierarchy_text + sub_chunk,
                        "metadata": {
                            "code": article.code,
                            "article": article.article,
                            "title": article.title,
                            "section": article.section,
                            "part": f"{i+1}/{len(sub_chunks)}",
                            **article.metadata
                        }
                    })
        
        return chunks
    
    def _split_article(self, text: str) -> List[str]:
        """Split large article text into overlapping chunks"""
        chunks = []
        
        # Try to split at natural boundaries (points)
        points = re.split(r'(?=^\d+\))', text, flags=re.MULTILINE)
        
        current_chunk = ""
        for point in points:
            if len(current_chunk) + len(point) <= self.max_chunk_size:
                current_chunk += point
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = point
        
        if current_chunk:
            chunks.append(current_chunk.strip())
        
        # Add overlap between chunks
        if len(chunks) > 1 and self.overlap > 0:
            overlapped_chunks = []
            for i, chunk in enumerate(chunks):
                if i > 0:
                    # Add end of previous chunk
                    prev_overlap = chunks[i-1][-self.overlap:]
                    chunk = prev_overlap + "\n...\n" + chunk
                
                if i < len(chunks) - 1:
                    # Add beginning of next chunk
                    next_overlap = chunks[i+1][:self.overlap]
                    chunk = chunk + "\n...\n" + next_overlap
                
                overlapped_chunks.append(chunk)
            
            return overlapped_chunks
        
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
    from typing import Tuple
    
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
        "average_chunk_size": sum(len(c["text"]) for c in chunks) / len(chunks) if chunks else 0,
        "sections_found": len(set(a.section for a in articles if a.section)),
        "parts_found": len(set(a.metadata.get("hierarchy", {}).get("part") for a in articles if a.metadata.get("hierarchy", {}).get("part"))),
        "divisions_found": len(set(a.metadata.get("hierarchy", {}).get("division") for a in articles if a.metadata.get("hierarchy", {}).get("division"))),
        "chapters_found": len(set(a.metadata.get("hierarchy", {}).get("chapter") for a in articles if a.metadata.get("hierarchy", {}).get("chapter")))
    }
    
    # Save chunks
    output_file = Path(output_dir) / f"{code_type}_chunks.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump({
            "code": code_type,
            "created_at": datetime.now().isoformat(),
            "statistics": stats,
            "chunks": chunks
        }, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Saved {len(chunks)} chunks to {output_file}")
    logger.info(f"Statistics: {stats}")
    
    return chunks, stats

# Example usage
if __name__ == "__main__":
    # Test the parser
    parser = PolishStatuteParser("KC")
    
    # Test hierarchy detection
    test_text = """
    CZĘŚĆ OGÓLNA
    
    DZIAŁ I: PRZEPISY WSTĘPNE
    
    Rozdział I: Zakres obowiązywania
    
    Art. 1. Kodeks cywilny reguluje stosunki cywilnoprawne między osobami fizycznymi i osobami prawnymi.
    
    Art. 2. § 1. Przepisy kodeksu stosuje się do stosunków cywilnoprawnych z udziałem konsumentów.
    § 2. Konsumentem jest osoba fizyczna dokonująca czynności prawnej niezwiązanej bezpośrednio z jej działalnością gospodarczą lub zawodową.
    """
    
    articles = parser._parse_text(test_text)
    
    for article in articles:
        print(f"\nArticle {article.article}:")
        print(f"  Section: {article.section}")
        print(f"  Hierarchy: {article.metadata.get('hierarchy', {})}")
        print(f"  Content preview: {article.content[:100]}...")
