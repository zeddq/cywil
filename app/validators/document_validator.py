"""
Document validation service for Polish legal documents.
Validates documents at pipeline boundaries and ensures data integrity.
"""

import re
from typing import Any, Dict, List, Tuple, Optional
from pydantic import ValidationError

from app.embedding_models.pipeline_schemas import (
    RawDocument,
    ProcessedChunk,
    EmbeddedChunk,
    LegalExtraction,
    ValidationResult,
    DocumentType
)


class DocumentValidator:
    """Validates documents at pipeline boundaries and ensures Polish legal format compliance."""
    
    # Polish legal document patterns
    POLISH_LEGAL_PATTERNS = {
        'case_number': r'[IVX]+ [A-Z]+ \d+/\d+',
        'case_number_extended': r'(Sygn\.\s*akt\s*)?([IVX]+ [A-Z]+ \d+/\d+)',
        'article': r'art\.\s*\d+',
        'paragraph': r'§\s*\d+',
        'statute_ref': r'(k\.c\.|k\.p\.c\.|k\.k\.|k\.p\.k\.)',
        'court_name': r'Sąd\s+(Najwyższy|Apelacyjny|Okręgowy|Rejonowy)',
        'date_polish': r'\d{1,2}\s+(stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia)\s+\d{4}\s*r\.',
        'date_standard': r'\d{1,2}\.\d{1,2}\.\d{4}',
        'legal_citation': r'art\.\s*\d+(\s*§\s*\d+)?\s*(k\.c\.|k\.p\.c\.|KC|KPC)',
        'person_name': r'[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+',
        'company_name': r'[A-ZĄĆĘŁŃÓŚŹŻ][^.]*(?:sp\.\s*z\s*o\.o\.|S\.A\.|s\.c\.|s\.j\.)',
        'currency_amount': r'\d+(?:\.\d{2})?\s*zł',
        'court_decision': r'(oddala|uwzględnia|uchyla|zmienia|odrzuca)'
    }
    
    # Required sections for different document types
    REQUIRED_SECTIONS = {
        DocumentType.SUPREME_COURT: [
            'Sygn. akt',
            'WYROK',
            'UZASADNIENIE'
        ],
        DocumentType.CIVIL_CODE: [
            'Art.',
            'Kodeks cywilny'
        ],
        DocumentType.CIVIL_PROCEDURE: [
            'Art.',
            'Kodeks postępowania cywilnego'
        ]
    }
    
    @classmethod
    def validate_legal_document(cls, content: str, document_type: Optional[DocumentType] = None) -> ValidationResult:
        """
        Validate Polish legal document format and content.
        
        Args:
            content: Document content to validate
            document_type: Expected document type
            
        Returns:
            ValidationResult with validation status and errors
        """
        errors = []
        warnings = []
        
        if not content or len(content.strip()) == 0:
            errors.append("Document content is empty")
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                stage="document_validation"
            )
        
        # Check document length
        if len(content) < 100:
            warnings.append("Document content is very short, may be incomplete")
        elif len(content) > 500000:
            warnings.append("Document content is very long, may affect processing performance")
        
        # Type-specific validation
        if document_type == DocumentType.SUPREME_COURT:
            cls._validate_supreme_court_document(content, errors, warnings)
        elif document_type is not None and document_type in [DocumentType.CIVIL_CODE, DocumentType.CIVIL_PROCEDURE]:
            cls._validate_statute_document(content, document_type, errors, warnings)
        
        # General Polish legal document validation
        cls._validate_general_legal_format(content, errors, warnings)
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stage="document_validation"
        )
    
    @classmethod
    def _validate_supreme_court_document(cls, content: str, errors: List[str], warnings: List[str]) -> None:
        """Validate Supreme Court ruling format."""
        required_sections = cls.REQUIRED_SECTIONS[DocumentType.SUPREME_COURT]
        
        for section in required_sections:
            if section not in content:
                errors.append(f"Missing required section: {section}")
        
        # Check for case number
        case_number_pattern = cls.POLISH_LEGAL_PATTERNS['case_number_extended']
        if not re.search(case_number_pattern, content, re.IGNORECASE):
            errors.append("No valid case number found")
        
        # Check for court composition
        if not re.search(r'Sąd\s+Najwyższy\s+w\s+składzie', content, re.IGNORECASE):
            warnings.append("Court composition section not found")
        
        # Check for legal basis references
        if not re.search(cls.POLISH_LEGAL_PATTERNS['article'], content, re.IGNORECASE):
            warnings.append("No article references found")
        
        # Check for decision
        if not re.search(cls.POLISH_LEGAL_PATTERNS['court_decision'], content, re.IGNORECASE):
            warnings.append("Court decision not clearly identified")
    
    @classmethod
    def _validate_statute_document(cls, content: str, document_type: DocumentType, errors: List[str], warnings: List[str]) -> None:
        """Validate statute document format."""
        if document_type == DocumentType.CIVIL_CODE and 'Kodeks cywilny' not in content:
            errors.append("Civil Code title not found")
        elif document_type == DocumentType.CIVIL_PROCEDURE and 'Kodeks postępowania cywilnego' not in content:
            errors.append("Civil Procedure Code title not found")
        
        # Check for article structure
        if not re.search(r'Art\.\s*\d+', content):
            errors.append("No article numbers found")
        
        # Check for proper article formatting
        article_matches = re.findall(r'Art\.\s*(\d+)', content)
        if len(article_matches) == 0:
            errors.append("No properly formatted articles found")
    
    @classmethod
    def _validate_general_legal_format(cls, content: str, errors: List[str], warnings: List[str]) -> None:
        """Validate general Polish legal document formatting."""
        # Check for Polish characters
        polish_chars = 'ąćęłńóśźżĄĆĘŁŃÓŚŹŻ'
        if not any(char in content for char in polish_chars):
            warnings.append("No Polish diacritical marks found - document may not be in Polish")
        
        # Check for legal terminology
        legal_terms = ['prawo', 'ustawa', 'przepis', 'artykuł', 'sąd', 'wyrok', 'postanowienie']
        found_terms = sum(1 for term in legal_terms if term in content.lower())
        if found_terms < 2:
            warnings.append("Few legal terms found - document may not be legal content")
        
        # Check for proper sentence structure
        sentences = content.split('.')
        short_sentences = [s for s in sentences if len(s.strip()) < 10]
        if len(short_sentences) > len(sentences) * 0.3:
            warnings.append("Many very short sentences found - document may be fragmented")
    
    @classmethod
    def validate_pipeline_transition(
        cls,
        input_data: Any,
        output_data: Any,
        stage: str
    ) -> ValidationResult:
        """
        Validate data integrity between pipeline stages.
        
        Args:
            input_data: Input data to the stage
            output_data: Output data from the stage
            stage: Pipeline stage name
            
        Returns:
            ValidationResult with validation status and errors
        """
        errors = []
        warnings = []
        
        try:
            if stage == "chunking":
                cls._validate_chunking_stage(input_data, output_data, errors, warnings)
            elif stage == "embedding":
                cls._validate_embedding_stage(input_data, output_data, errors, warnings)
            elif stage == "extraction":
                cls._validate_extraction_stage(input_data, output_data, errors, warnings)
            elif stage == "parsing":
                cls._validate_parsing_stage(input_data, output_data, errors, warnings)
            else:
                warnings.append(f"Unknown pipeline stage: {stage}")
        
        except Exception as e:
            errors.append(f"Pipeline validation error: {str(e)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stage=stage
        )
    
    @classmethod
    def _validate_chunking_stage(cls, input_data: RawDocument, output_data: List[ProcessedChunk], errors: List[str], warnings: List[str]) -> None:
        """Validate chunking stage output."""
        if not output_data or len(output_data) == 0:
            errors.append("No chunks produced from document")
            return
        
        # Check content preservation
        total_chunk_length = sum(len(chunk.content) for chunk in output_data)
        original_length = len(input_data.content)
        
        if total_chunk_length < original_length * 0.85:
            errors.append(f"Significant content loss during chunking: {total_chunk_length}/{original_length} characters preserved")
        elif total_chunk_length < original_length * 0.95:
            warnings.append(f"Minor content loss during chunking: {total_chunk_length}/{original_length} characters preserved")
        
        # Check chunk ordering
        for i, chunk in enumerate(output_data):
            if chunk.chunk_index != i:
                errors.append(f"Chunk ordering error: chunk at position {i} has index {chunk.chunk_index}")
            
            # Check chunk belongs to input document
            if chunk.document_id != input_data.id:
                errors.append(f"Chunk {chunk.chunk_id} has wrong document_id: {chunk.document_id} != {input_data.id}")
        
        # Check for overlapping chunks
        for i in range(len(output_data) - 1):
            current_chunk = output_data[i]
            next_chunk = output_data[i + 1]
            
            if current_chunk.end_char > next_chunk.start_char:
                warnings.append(f"Overlapping chunks detected: chunk {i} ends at {current_chunk.end_char}, chunk {i+1} starts at {next_chunk.start_char}")
    
    @classmethod
    def _validate_embedding_stage(cls, input_data: List[ProcessedChunk], output_data: List[EmbeddedChunk], errors: List[str], warnings: List[str]) -> None:
        """Validate embedding stage output."""
        if len(input_data) != len(output_data):
            errors.append(f"Chunk count mismatch: input {len(input_data)}, output {len(output_data)}")
        
        for i, embedded_chunk in enumerate(output_data):
            if not embedded_chunk.embedding:
                errors.append(f"Missing embedding for chunk {embedded_chunk.chunk_id}")
            elif len(embedded_chunk.embedding) < 300:
                errors.append(f"Embedding dimension too small for chunk {embedded_chunk.chunk_id}: {len(embedded_chunk.embedding)}")
            
            # Check if embedding model is specified
            if not embedded_chunk.embedding_model:
                warnings.append(f"Embedding model not specified for chunk {embedded_chunk.chunk_id}")
    
    @classmethod
    def _validate_extraction_stage(cls, input_data: RawDocument, output_data: LegalExtraction, errors: List[str], warnings: List[str]) -> None:
        """Validate legal information extraction."""
        # Check if extraction found legal references when they exist in input
        input_content = input_data.content.lower()
        
        if "art." in input_content and not output_data.legal_basis:
            errors.append("Failed to extract legal references despite articles being present")
        
        # Check case number extraction for Supreme Court documents
        if input_data.document_type == DocumentType.SUPREME_COURT:
            case_pattern = cls.POLISH_LEGAL_PATTERNS['case_number_extended']
            if re.search(case_pattern, input_data.content, re.IGNORECASE) and not output_data.case_number:
                warnings.append("Case number appears to be present but was not extracted")
        
        # Validate extracted case number format if present
        if output_data.case_number:
            case_pattern = cls.POLISH_LEGAL_PATTERNS['case_number']
            if not re.match(case_pattern, output_data.case_number):
                errors.append(f"Extracted case number has invalid format: {output_data.case_number}")
    
    @classmethod
    def _validate_parsing_stage(cls, input_data: bytes, output_data: RawDocument, errors: List[str], warnings: List[str]) -> None:
        """Validate PDF parsing stage."""
        if not output_data.content:
            errors.append("No text content extracted from PDF")
        elif len(output_data.content) < 100:
            warnings.append("Very little text content extracted - PDF may be image-based or corrupted")
        
        # Check for common parsing artifacts
        if output_data.content.count('�') > 10:
            warnings.append("Many unicode replacement characters found - encoding issues during parsing")
        
        # Check for reasonable text structure
        if len(output_data.content.split()) < 50:
            warnings.append("Very few words extracted - document may not have processed correctly")
    
    @classmethod
    def validate_batch_consistency(cls, documents: List[Any], stage: str) -> ValidationResult:
        """
        Validate consistency across a batch of documents.
        
        Args:
            documents: List of documents to validate
            stage: Pipeline stage name
            
        Returns:
            ValidationResult with batch validation status
        """
        errors = []
        warnings = []
        
        if not documents:
            errors.append("Empty document batch")
            return ValidationResult(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                stage=f"batch_{stage}"
            )
        
        # Check for duplicate document IDs
        if hasattr(documents[0], 'document_id'):
            doc_ids = [doc.document_id for doc in documents]
            duplicates = [doc_id for doc_id in set(doc_ids) if doc_ids.count(doc_id) > 1]
            if duplicates:
                errors.append(f"Duplicate document IDs found: {duplicates}")
        
        # Check for consistency in embedding dimensions
        if hasattr(documents[0], 'embedding'):
            embedding_dims = [len(doc.embedding) for doc in documents if doc.embedding]
            if len(set(embedding_dims)) > 1:
                errors.append(f"Inconsistent embedding dimensions: {set(embedding_dims)}")
        
        # Check for consistency in embedding models
        if hasattr(documents[0], 'embedding_model'):
            models = [doc.embedding_model for doc in documents if hasattr(doc, 'embedding_model') and doc.embedding_model]
            if len(set(models)) > 1:
                warnings.append(f"Multiple embedding models used: {set(models)}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            stage=f"batch_{stage}"
        )
    
    @classmethod
    def extract_polish_entities(cls, content: str) -> Dict[str, List[str]]:
        """
        Extract Polish legal entities from document content.
        
        Args:
            content: Document content
            
        Returns:
            Dictionary with extracted entities by type
        """
        entities = {
            'case_numbers': [],
            'articles': [],
            'courts': [],
            'dates': [],
            'persons': [],
            'companies': [],
            'amounts': []
        }
        
        # Extract case numbers
        case_matches = re.findall(cls.POLISH_LEGAL_PATTERNS['case_number_extended'], content, re.IGNORECASE)
        entities['case_numbers'] = [match[1] if isinstance(match, tuple) else match for match in case_matches]
        
        # Extract articles
        entities['articles'] = re.findall(cls.POLISH_LEGAL_PATTERNS['legal_citation'], content, re.IGNORECASE)
        
        # Extract court names
        entities['courts'] = re.findall(cls.POLISH_LEGAL_PATTERNS['court_name'], content, re.IGNORECASE)
        
        # Extract dates
        polish_dates = re.findall(cls.POLISH_LEGAL_PATTERNS['date_polish'], content, re.IGNORECASE)
        standard_dates = re.findall(cls.POLISH_LEGAL_PATTERNS['date_standard'], content)
        entities['dates'] = polish_dates + standard_dates
        
        # Extract person names (basic pattern)
        entities['persons'] = re.findall(cls.POLISH_LEGAL_PATTERNS['person_name'], content)
        
        # Extract company names
        entities['companies'] = re.findall(cls.POLISH_LEGAL_PATTERNS['company_name'], content, re.IGNORECASE)
        
        # Extract currency amounts
        entities['amounts'] = re.findall(cls.POLISH_LEGAL_PATTERNS['currency_amount'], content)
        
        return entities
