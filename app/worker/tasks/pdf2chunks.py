import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union, Match

import pdfplumber

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class ArticleChunk:
    """Represents a single article or section from the legal code"""

    code: str  # KC or KPC
    article: str  # e.g., "415", "415¹", "415§2"
    title: str  # Article title if present
    path: str
    metadata: Dict  # Additional metadata
    content: Optional[str] = None  # Full text of the article
    book: Optional[str] = None
    part: Optional[str] = None
    division: Optional[str] = None
    chapter: Optional[str] = None
    subdivision: Optional[str] = None


@dataclass
class HierarchyElement:
    name: str
    keyword: str
    level: int
    pattern: re.Pattern
    is_optional: bool = False
    current_name: Optional[str] = None
    current_title: Optional[str] = None


class PolishStatuteParser:
    """Parser specifically designed for Polish legal statutes with correct hierarchy"""

    # Polish legal document hierarchy:
    # 1. Księga (Book) - highest level
    # 2. Część (Part)
    # 3. Tytuł (Title)
    # 4. Dział (Division)
    # 5. Rozdział (Chapter)
    # 6. Oddział (Subdivision)
    # 7. Artykuł (Article) - lowest level

    def __init__(self, code_type: str = "KC"):
        """
        Initialize parser for specific code type

        Args:
            code_type: Type of code (KC or KPC)
        """
        self.code_type = code_type
        self.HIERARCHY_ELEMENTS = [
            HierarchyElement(
                name="book",
                keyword="KSIĘGA",
                level=1 if self.code_type == "KC" else 2,
                pattern=re.compile(r"^KSIĘGA\s+(\w+)", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="part",
                keyword="CZĘŚĆ",
                level=2 if self.code_type == "KC" else 1,
                pattern=re.compile(r"^CZĘŚĆ\s+(\w+)", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="title",
                keyword="TYTUŁ",
                level=3,
                pattern=re.compile(r"^TYTUŁ\s+([IVXLCDM]+)(?:\s|$)", re.MULTILINE),
            ),
            HierarchyElement(
                name="division",
                keyword="DZIAŁ",
                level=4,
                pattern=re.compile(r"^DZIAŁ\s+([IVXLCDM]+)(?:\s|$)", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="chapter",
                keyword="ROZDZIAŁ",
                level=5,
                pattern=re.compile(r"^Rozdział\s+([IVXLCDM]+)(?:\s|$)", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="subdivision",
                keyword="ODDZIAŁ",
                level=6,
                pattern=re.compile(r"^Oddział\s+([IVXLCDM]+)(?:\s|$)", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="article",
                keyword="Art.",
                level=7,
                pattern=re.compile(r"^Art\.\s*(\d+[¹²³⁴⁵⁶⁷⁸⁹]*)\s*\.", re.MULTILINE),
            ),
            HierarchyElement(
                name="deleted",
                keyword="uchylony",
                level=7,
                pattern=re.compile(r"\(uchylon[ya]\)|\(skreślon[ya]\)"),
                is_optional=True,
            ),
            HierarchyElement(
                name="paragraph",
                keyword="§",
                level=8,
                pattern=re.compile(r"^§\s*(\d+)\s*\.", re.MULTILINE),
                is_optional=True,
            ),
            HierarchyElement(
                name="point",
                keyword="pkt.",
                level=9,
                pattern=re.compile(r"^(\d+)\)", re.MULTILINE),
                is_optional=True,
            ),
        ]
        self.HIERARCHY_MAP = {element.name: element for element in self.HIERARCHY_ELEMENTS}
        self.KEYWORDS = [element.keyword for element in self.HIERARCHY_ELEMENTS]

    def _match_hierarchy_element(self, text: Optional[Union[str, Match[str]]]) -> Optional[Tuple[Match[str], HierarchyElement]]:
        """Try matching any hierarchy element"""
        if text is None:
            return None
        # Handle both str and Match objects
        if isinstance(text, str):
            search_text = text
        else:
            search_text = text.group()
        for element in self.HIERARCHY_ELEMENTS:
            match = element.pattern.search(search_text)
            if match:
                return match, element
        return None

    def _process_hierarchy_element(
        self,
        match: List[str],
        next_line: Optional[Match[str]],
        element: HierarchyElement,
    ):
        """Process a hierarchy element"""
        match_list = list(filter(lambda x: x is not None, match))
        if len(match_list) == 1:
            element.current_name = match_list[0]
        elif len(match_list) == 2:
            element.current_name = f"{element.keyword} {match_list[1]}"
            if element.level < self.HIERARCHY_MAP[
                "article"
            ].level and not self._match_hierarchy_element(next_line.group() if next_line else ""):
                element.current_title = next_line.group() if next_line else None
            else:
                element.current_title = None
        elif len(match_list) == 3:
            element.current_name = f"{element.keyword} {match_list[1]}"
            element.current_title = match_list[2]
        else:
            raise ValueError(
                f"Unexpected number of groups: {len(match_list)} for {match}, {next_line}, {element}"
            )

        for el in self.HIERARCHY_ELEMENTS:
            if el.name != element.name and el.level >= element.level:
                el.current_name = None
                el.current_title = None

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
        article_splits = self.HIERARCHY_MAP["article"].pattern.split(text)
        if article_splits and article_splits[0].strip():
            self._update_structure_context(article_splits[0])

        # Process each article (article is a hierarchy element)
        i = 1
        while i < len(article_splits) - 1:
            article = article_splits[i]
            article_content = article_splits[i + 1]

            self._process_hierarchy_element(["Art.", article], None, self.HIERARCHY_MAP["article"])

            # Find the end of this article (start of next article or end of text)
            next_article_match = self.HIERARCHY_MAP["article"].pattern.search(article_content)
            if next_article_match:
                article_text = article_content[: next_article_match.start()]
                remaining_text = article_content[next_article_match.start() :]
                article_splits[i + 1] = remaining_text
            else:
                article_text = article_content

            # Update current section/chapter if found
            article_text = self._update_structure_context(article_text)

            # Check if article is deleted
            if self.HIERARCHY_MAP["deleted"].pattern.search(article_text[:100]):
                metadata = {"status": "deleted", "type": "article"}
            else:
                metadata = {"status": "active", "type": "article"}

            # Add hierarchy information
            hierarchy_data = self._get_hierarchy_metadata()
            metadata.update(hierarchy_data)

            # Parse paragraphs within the article
            paragraphs = self._parse_paragraphs(article_text)

            if paragraphs:
                # Create separate chunks for each paragraph
                for para_num, para_content in paragraphs.items():
                    self._process_hierarchy_element(
                        ["§", para_num], None, self.HIERARCHY_MAP["paragraph"]
                    )
                    chunk_id = f"{article}§{para_num}" if para_num != "main" else article
                    chunks.append(
                        ArticleChunk(
                            code=self.code_type,
                            article=chunk_id,
                            content=para_content,
                            book=self.HIERARCHY_MAP["book"].current_name,
                            part=self.HIERARCHY_MAP["part"].current_name,
                            title=self.HIERARCHY_MAP["title"].current_name or "",
                            division=self.HIERARCHY_MAP["division"].current_name,
                            chapter=self.HIERARCHY_MAP["chapter"].current_name,
                            subdivision=self.HIERARCHY_MAP["subdivision"].current_name,
                            path=self._get_current_section_path(),
                            metadata={**metadata, "paragraph": para_num},
                        )
                    )
            else:
                # Single chunk for the entire article
                chunks.append(
                    ArticleChunk(
                        code=self.code_type,
                        article=article,
                        content=article_text.strip(),
                        book=self.HIERARCHY_MAP["book"].current_name,
                        part=self.HIERARCHY_MAP["part"].current_name,
                        title=self.HIERARCHY_MAP["title"].current_name or "",
                        division=self.HIERARCHY_MAP["division"].current_name,
                        chapter=self.HIERARCHY_MAP["chapter"].current_name,
                        subdivision=self.HIERARCHY_MAP["subdivision"].current_name,
                        path=self._get_current_section_path(),
                        metadata=metadata,
                    )
                )

            i += 2

        return chunks

    def _parse_paragraphs(self, article_text: str) -> Dict[str, str]:
        """Parse paragraphs (§) within an article"""
        paragraphs = {}

        para_splits = self.HIERARCHY_MAP["paragraph"].pattern.split(article_text.strip())

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
                next_para_match = self.HIERARCHY_MAP["paragraph"].pattern.search(para_content)
                if next_para_match:
                    para_text = para_content[: next_para_match.start()]
                else:
                    para_text = para_content

                paragraphs[para_num] = para_text.strip()
                i += 2
        else:
            # No paragraphs, treat as single content
            if article_text.strip():
                paragraphs["main"] = article_text.strip()

        return paragraphs

    def _update_structure_context(self, text: str) -> str:
        """Update current hierarchy based on text"""

        non_hierarchy_text = ""
        hierarchy_found = False
        # Split text into lines for more accurate parsing
        lines = text.split("\n")

        for i, line in enumerate(lines):
            line = line.strip()

            # Check for book (first level)
            match_element = self._match_hierarchy_element(line)
            if match_element and match_element[1].level < self.HIERARCHY_MAP["article"].level:
                next_line_match = None
                if i + 1 < len(lines):
                    next_line_result = self._match_hierarchy_element(lines[i + 1].strip())
                    if next_line_result:
                        next_line_match = next_line_result[0]
                        
                self._process_hierarchy_element(
                    [match_element[0].group(0)] + list(match_element[0].groups()),
                    next_line_match,
                    match_element[1],
                )
                hierarchy_found = True
            elif not hierarchy_found:
                non_hierarchy_text += line + "\n"

        return non_hierarchy_text

    def _get_current_section_path(self) -> str:
        """Get the current section path as a string"""
        path_parts = []

        elems = sorted(self.HIERARCHY_ELEMENTS, key=lambda x: x.level)
        for elem in elems:
            part = ""
            if elem.current_name:
                part = elem.current_name
            if elem.current_title:
                part += f": {elem.current_title}"
            if part:
                path_parts.append(part)

        return " > ".join(path_parts) if path_parts else ""

    def _get_hierarchy_metadata(self) -> Dict[str, Any]:
        """Get current hierarchy as metadata dictionary"""
        return {
            "book": self.HIERARCHY_MAP["book"].current_name,
            "book_name": self.HIERARCHY_MAP["book"].current_title,
            "part": self.HIERARCHY_MAP["part"].current_name,
            "part_name": self.HIERARCHY_MAP["part"].current_title,
            "title": self.HIERARCHY_MAP["title"].current_name,
            "title_name": self.HIERARCHY_MAP["title"].current_title,
            "division": self.HIERARCHY_MAP["division"].current_name,
            "division_name": self.HIERARCHY_MAP["division"].current_title,
            "chapter": self.HIERARCHY_MAP["chapter"].current_name,
            "chapter_name": self.HIERARCHY_MAP["chapter"].current_title,
            "subdivision": self.HIERARCHY_MAP["subdivision"].current_name,
            "subdivision_name": self.HIERARCHY_MAP["subdivision"].current_title,
        }


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
            # Skip articles with no content
            if not article.content:
                continue
                
            # Create chunk ID with hierarchy information
            chunk_base_id = f"{article.code}_art_{article.article}"

            # Include hierarchy in chunk for better search
            hierarchy_text = ""
            if article.path:
                hierarchy_text = f"[{article.path}]\n"

            # For small articles, keep as single chunk
            if len(article.content) <= self.max_chunk_size:
                chunks.append(
                    {
                        "chunk_id": chunk_base_id,
                        "text": hierarchy_text + article.content,
                        "metadata": {
                            "code": article.code,
                            "article": article.article,
                            "title": article.title,
                            "path": article.path,
                            **article.metadata,
                        },
                    }
                )
            else:
                # Split large articles intelligently
                sub_chunks = self._split_article(article.content)

                for i, sub_chunk in enumerate(sub_chunks):
                    chunks.append(
                        {
                            "chunk_id": f"{chunk_base_id}_part{i+1}",
                            "text": hierarchy_text + sub_chunk,
                            "metadata": {
                                "code": article.code,
                                "article": article.article,
                                "title": article.title,
                                "path": article.path,
                                "part": f"{i+1}/{len(sub_chunks)}",
                                **article.metadata,
                            },
                        }
                    )

        return chunks

    def _split_article(self, text: str) -> List[str]:
        """Split large article text into overlapping chunks"""
        chunks = []

        # Try to split at natural boundaries (points)
        points = re.split(r"(?=^\d+\))", text, flags=re.MULTILINE)

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
                    prev_overlap = chunks[i - 1][-self.overlap :]
                    chunk = prev_overlap + "\n...\n" + chunk

                if i < len(chunks) - 1:
                    # Add beginning of next chunk
                    next_overlap = chunks[i + 1][: self.overlap]
                    chunk = chunk + "\n...\n" + next_overlap

                overlapped_chunks.append(chunk)

            return overlapped_chunks

        return chunks


def process_statute_pdf(
    pdf_path: str, code_type: str, output_dir: str = "data/chunks"
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
        "average_chunk_size": (sum(len(c["text"]) for c in chunks) / len(chunks) if chunks else 0),
        "sections_found": len(set(a.path for a in articles if a.path)),
        "parts_found": len(
            set(
                a.metadata.get("hierarchy", {}).get("part")
                for a in articles
                if a.metadata.get("hierarchy", {}).get("part")
            )
        ),
        "divisions_found": len(
            set(
                a.metadata.get("hierarchy", {}).get("division")
                for a in articles
                if a.metadata.get("hierarchy", {}).get("division")
            )
        ),
        "chapters_found": len(
            set(
                a.metadata.get("hierarchy", {}).get("chapter")
                for a in articles
                if a.metadata.get("hierarchy", {}).get("chapter")
            )
        ),
    }

    # Save chunks
    output_file = Path(output_dir) / f"{code_type}_chunks.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "code": code_type,
                "created_at": datetime.now().isoformat(),
                "statistics": stats,
                "chunks": chunks,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

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
        print(f"  Section: {article.path}")
        print(f"  Hierarchy: {article.metadata.get('hierarchy', {})}")
        print(f"  Content preview: {(article.content or '')[:100]}...")
