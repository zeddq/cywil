"""
Test data loader for legal document fixtures.
"""

from pathlib import Path
from typing import Dict, List

from app.models.pipeline_schemas import RawDocument, DocumentType


class LegalDocumentLoader:
    """Utility class for loading test document fixtures."""
    
    FIXTURES_PATH = Path(__file__).parent
    
    @classmethod
    def load_valid_documents(cls) -> List[RawDocument]:
        """Load all valid test documents."""
        documents = []
        valid_path = cls.FIXTURES_PATH / "valid"
        
        for file_path in valid_path.glob("*.txt"):
            content = file_path.read_text(encoding="utf-8")
            doc_type = cls._determine_document_type(file_path.name, content)
            
            document = RawDocument(
                id=file_path.stem.upper(),
                content=content,
                document_type=doc_type,
                source_path=str(file_path),
                metadata={"fixture_type": "valid"}
            )
            documents.append(document)
        
        return documents
    
    @classmethod
    def load_invalid_documents(cls) -> List[RawDocument]:
        """Load all invalid test documents."""
        documents = []
        invalid_path = cls.FIXTURES_PATH / "invalid"
        
        for file_path in invalid_path.glob("*.txt"):
            content = file_path.read_text(encoding="utf-8")
            
            # For invalid documents, we still need to assign a type for testing
            document = RawDocument(
                id=file_path.stem.upper(),
                content=content,
                document_type=DocumentType.SUPREME_COURT,  # Default type
                source_path=str(file_path),
                metadata={"fixture_type": "invalid"}
            )
            documents.append(document)
        
        return documents
    
    @classmethod
    def load_edge_case_documents(cls) -> List[RawDocument]:
        """Load all edge case test documents."""
        documents = []
        edge_path = cls.FIXTURES_PATH / "edge_cases"
        
        for file_path in edge_path.glob("*.txt"):
            content = file_path.read_text(encoding="utf-8")
            doc_type = cls._determine_document_type(file_path.name, content)
            
            document = RawDocument(
                id=file_path.stem.upper(),
                content=content,
                document_type=doc_type,
                source_path=str(file_path),
                metadata={"fixture_type": "edge_case"}
            )
            documents.append(document)
        
        return documents
    
    @classmethod
    def load_document_by_name(cls, filename: str) -> RawDocument:
        """Load a specific document by filename."""
        # Try all subdirectories
        for subdir in ["valid", "invalid", "edge_cases"]:
            file_path = cls.FIXTURES_PATH / subdir / f"{filename}.txt"
            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                doc_type = cls._determine_document_type(filename, content)
                
                return RawDocument(
                    id=filename.upper(),
                    content=content,
                    document_type=doc_type,
                    source_path=str(file_path),
                    metadata={"fixture_type": subdir}
                )
        
        raise FileNotFoundError(f"Document {filename}.txt not found in fixtures")
    
    @classmethod
    def _determine_document_type(cls, filename: str, content: str) -> DocumentType:
        """Determine document type based on filename and content."""
        filename_lower = filename.lower()
        content_lower = content.lower()
        
        if "wyrok" in filename_lower or "postanowienie" in filename_lower:
            return DocumentType.SUPREME_COURT
        elif "kodeks_cywilny" in filename_lower or "art" in content_lower:
            if "postępowania" in content_lower or "k.p.c." in content_lower:
                return DocumentType.CIVIL_PROCEDURE
            else:
                return DocumentType.CIVIL_CODE
        else:
            # Default to Supreme Court for legal documents
            return DocumentType.SUPREME_COURT
    
    @classmethod
    def get_test_scenarios(cls) -> Dict[str, List[str]]:
        """Get test scenarios mapped to document names."""
        return {
            "valid_parsing": [
                "sample_wyrok_sn",
                "kodeks_cywilny_art415",
                "postanowienie_sa"
            ],
            "invalid_documents": [
                "empty",
                "non_legal",
                "corrupted"
            ],
            "edge_cases": [
                "very_short",
                "mixed_language"
            ],
            "case_number_extraction": [
                "sample_wyrok_sn",
                "postanowienie_sa"
            ],
            "article_extraction": [
                "kodeks_cywilny_art415",
                "sample_wyrok_sn"
            ],
            "polish_validation": [
                "sample_wyrok_sn",
                "mixed_language",
                "non_legal"
            ]
        }