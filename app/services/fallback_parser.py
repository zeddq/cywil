"""
Fallback parser for when AI services fail.
Provides regex-based parsing capabilities to ensure system reliability.
"""

import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.embedding_models.pipeline_schemas import (
    LegalExtraction,
    FallbackResult,
    DocumentType,
    ProcessedChunk,
    RawDocument
)


class FallbackParser:
    """
    Regex-based parser for when AI services are unavailable.
    Provides basic extraction capabilities using pattern matching.
    """
    
    # Enhanced Polish legal patterns
    PATTERNS = {
        # Case number patterns
        'case_number': r'Sygn\.\s*akt\s*([IVX]+ [A-Z]+ \d+/\d+)',
        'case_number_simple': r'([IVX]+ [A-Z]+ \d+/\d+)',
        
        # Date patterns
        'date_polish': r'(\d{1,2})\s+(stycznia|lutego|marca|kwietnia|maja|czerwca|lipca|sierpnia|września|października|listopada|grudnia)\s+(\d{4})\s*r\.',
        'date_standard': r'(\d{1,2})\.(\d{1,2})\.(\d{4})',
        'date_iso': r'(\d{4})-(\d{1,2})-(\d{1,2})',
        
        # Legal references
        'article_full': r'art\.\s*(\d+)(\s*§\s*(\d+))?\s*(k\.c\.|k\.p\.c\.|KC|KPC)',
        'article_simple': r'art\.\s*(\d+)',
        'paragraph': r'§\s*(\d+)',
        
        # Court and parties
        'court_composition': r'Sąd\s+(Najwyższy|Apelacyjny|Okręgowy|Rejonowy)[^.]*w\s+składzie[^.]*',
        'court_name': r'Sąd\s+(Najwyższy|Apelacyjny|Okręgowy|Rejonowy)(?:\s+w\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)?',
        'judge_name': r'(?:SSN|Sędzia|S\.)\s+([A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][a-ząćęłńóśźż]+)*)',
        
        # Parties
        'plaintiff': r'(?:z\s+powództwa|powód[^:]*)[\s:]+([A-ZĄĆĘŁŃÓŚŹŻ][^,\n]*?)(?:\s+przeciwko|\s+o\s+)',
        'defendant': r'przeciwko\s+([A-ZĄĆĘŁŃÓŚŹŻ][^,\n]*?)(?:\s+o\s+|\n)',
        'company': r'([A-ZĄĆĘŁŃÓŚŹŻ][^.]*?(?:sp\.\s*z\s*o\.o\.|S\.A\.|s\.c\.|s\.j\.))',
        
        # Decision types
        'decision_reject': r'(oddala|odrzuca)\s+(?:powództwo|skargę|zażalenie|kasację)',
        'decision_accept': r'(uwzględnia|przyjmuje)\s+(?:powództwo|skargę|zażalenie|kasację)',
        'decision_change': r'(zmienia|uchyla)\s+(?:wyrok|postanowienie|orzeczenie)',
        
        # Financial amounts
        'amount_zl': r'(\d+(?:\.\d{2})?)\s*zł',
        'amount_words': r'kwot[yęą]\s+([^.]*?)(?:złotych|zł)',
        
        # Legal basis sections
        'legal_basis_section': r'(?:podstawa\s+prawna|na\s+podstawie)[^.]*?(?:art\.[^.]*)',
        'reasoning_section': r'UZASADNIENIE[\s\S]*?(?=\n\n|\Z)',
        'decision_section': r'(?:WYROK|POSTANOWIENIE|ORZECZENIE)[\s\S]*?(?=UZASADNIENIE|\Z)'
    }
    
    # Polish month names to numbers
    POLISH_MONTHS = {
        'stycznia': 1, 'lutego': 2, 'marca': 3, 'kwietnia': 4,
        'maja': 5, 'czerwca': 6, 'lipca': 7, 'sierpnia': 8,
        'września': 9, 'października': 10, 'listopada': 11, 'grudnia': 12
    }
    
    @classmethod
    def extract_case_info(cls, text: str) -> FallbackResult:
        """
        Extract basic case information using regex patterns.
        
        Args:
            text: Document text content
            
        Returns:
            FallbackResult with extracted information
        """
        extraction = LegalExtraction(case_number=None, court=None, date=None, parties=[], legal_basis=[], decision=None, reasoning=None)
        errors = []
        confidence_scores = []
        
        try:
            # Extract case number
            case_number, case_confidence = cls._extract_case_number(text)
            if case_number:
                extraction.case_number = case_number
                confidence_scores.append(case_confidence)
            
            # Extract court information
            court, court_confidence = cls._extract_court(text)
            if court:
                extraction.court = court
                confidence_scores.append(court_confidence)
            
            # Extract date
            date, date_confidence = cls._extract_date(text)
            if date:
                extraction.date = date
                confidence_scores.append(date_confidence)
            
            # Extract parties
            parties, parties_confidence = cls._extract_parties(text)
            extraction.parties = parties
            if parties_confidence > 0:
                confidence_scores.append(parties_confidence)
            
            # Extract legal basis
            legal_basis, basis_confidence = cls._extract_legal_basis(text)
            extraction.legal_basis = legal_basis
            if basis_confidence > 0:
                confidence_scores.append(basis_confidence)
            
            # Extract decision
            decision, decision_confidence = cls._extract_decision(text)
            if decision:
                extraction.decision = decision
                confidence_scores.append(decision_confidence)
            
            # Extract reasoning
            reasoning = cls._extract_reasoning(text)
            if reasoning:
                extraction.reasoning = reasoning[:1000]  # Limit reasoning length
            
            # Calculate overall confidence
            overall_confidence = sum(confidence_scores) / len(confidence_scores) if confidence_scores else 0.1
            
            success = overall_confidence > 0.3 or len([x for x in [case_number, court, date] if x]) >= 2
            
            return FallbackResult(
                success=success,
                used_fallback=True,
                extraction=extraction,
                confidence=min(overall_confidence, 0.8),  # Cap fallback confidence
                method="regex_pattern_matching",
                errors=errors
            )
            
        except Exception as e:
            errors.append(f"Fallback parsing error: {str(e)}")
            return FallbackResult(
                success=False,
                used_fallback=True,
                extraction=None,
                confidence=0.0,
                method="regex_pattern_matching",
                errors=errors
            )
    
    @classmethod
    def _extract_case_number(cls, text: str) -> Tuple[Optional[str], float]:
        """Extract case number with confidence score."""
        # Try full pattern with "Sygn. akt"
        match = re.search(cls.PATTERNS['case_number'], text, re.IGNORECASE)
        if match:
            return match.group(1), 0.9
        
        # Try simple pattern
        match = re.search(cls.PATTERNS['case_number_simple'], text)
        if match:
            return match.group(1), 0.7
        
        return None, 0.0
    
    @classmethod
    def _extract_court(cls, text: str) -> Tuple[Optional[str], float]:
        """Extract court name with confidence score."""
        # Try court with composition
        match = re.search(cls.PATTERNS['court_composition'], text, re.IGNORECASE)
        if match:
            return match.group(0).strip(), 0.8
        
        # Try simple court name
        match = re.search(cls.PATTERNS['court_name'], text, re.IGNORECASE)
        if match:
            return match.group(0).strip(), 0.6
        
        return None, 0.0
    
    @classmethod
    def _extract_date(cls, text: str) -> Tuple[Optional[datetime], float]:
        """Extract date with confidence score."""
        # Try Polish date format
        match = re.search(cls.PATTERNS['date_polish'], text, re.IGNORECASE)
        if match:
            day, month_name, year = match.groups()
            month = cls.POLISH_MONTHS.get(month_name.lower())
            if month:
                try:
                    date = datetime(int(year), month, int(day))
                    return date, 0.9
                except ValueError:
                    pass
        
        # Try standard date format
        match = re.search(cls.PATTERNS['date_standard'], text)
        if match:
            day, month, year = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date, 0.8
            except ValueError:
                pass
        
        # Try ISO date format
        match = re.search(cls.PATTERNS['date_iso'], text)
        if match:
            year, month, day = match.groups()
            try:
                date = datetime(int(year), int(month), int(day))
                return date, 0.7
            except ValueError:
                pass
        
        return None, 0.0
    
    @classmethod
    def _extract_parties(cls, text: str) -> Tuple[List[str], float]:
        """Extract party names with confidence score."""
        parties = []
        confidence = 0.0
        
        # Extract plaintiff
        plaintiff_match = re.search(cls.PATTERNS['plaintiff'], text, re.IGNORECASE)
        if plaintiff_match:
            plaintiff = plaintiff_match.group(1).strip()
            parties.append(plaintiff)
            confidence += 0.4
        
        # Extract defendant
        defendant_match = re.search(cls.PATTERNS['defendant'], text, re.IGNORECASE)
        if defendant_match:
            defendant = defendant_match.group(1).strip()
            parties.append(defendant)
            confidence += 0.4
        
        # Extract companies
        company_matches = re.findall(cls.PATTERNS['company'], text, re.IGNORECASE)
        for company in company_matches:
            if company.strip() not in parties:
                parties.append(company.strip())
                confidence += 0.2
        
        return parties, min(confidence, 0.8)
    
    @classmethod
    def _extract_legal_basis(cls, text: str) -> Tuple[List[str], float]:
        """Extract legal article references with confidence score."""
        legal_basis = []
        confidence = 0.0
        
        # Extract full article references (art. X k.c.)
        full_matches = re.findall(cls.PATTERNS['article_full'], text, re.IGNORECASE)
        for match in full_matches:
            article_num = match[0]
            paragraph = match[2] if match[2] else ""
            code = match[3] if match[3] else ""
            
            if paragraph:
                ref = f"art. {article_num} § {paragraph} {code}"
            else:
                ref = f"art. {article_num} {code}"
            
            legal_basis.append(ref.strip())
            confidence += 0.3
        
        # Extract simple article references
        simple_matches = re.findall(cls.PATTERNS['article_simple'], text, re.IGNORECASE)
        for article_num in simple_matches:
            simple_ref = f"art. {article_num}"
            # Only add if not already covered by full matches
            if not any(simple_ref in basis for basis in legal_basis):
                legal_basis.append(simple_ref)
                confidence += 0.1
        
        # Remove duplicates while preserving order
        seen = set()
        unique_basis = []
        for item in legal_basis:
            if item not in seen:
                seen.add(item)
                unique_basis.append(item)
        
        return unique_basis, min(confidence, 0.8)
    
    @classmethod
    def _extract_decision(cls, text: str) -> Tuple[Optional[str], float]:
        """Extract court decision with confidence score."""
        # Check for rejection
        reject_match = re.search(cls.PATTERNS['decision_reject'], text, re.IGNORECASE)
        if reject_match:
            return f"Sąd {reject_match.group(1)} powództwo", 0.8
        
        # Check for acceptance
        accept_match = re.search(cls.PATTERNS['decision_accept'], text, re.IGNORECASE)
        if accept_match:
            return f"Sąd {accept_match.group(1)} powództwo", 0.8
        
        # Check for change/reversal
        change_match = re.search(cls.PATTERNS['decision_change'], text, re.IGNORECASE)
        if change_match:
            return f"Sąd {change_match.group(1)} orzeczenie", 0.7
        
        return None, 0.0
    
    @classmethod
    def _extract_reasoning(cls, text: str) -> Optional[str]:
        """Extract reasoning section if present."""
        match = re.search(cls.PATTERNS['reasoning_section'], text, re.IGNORECASE | re.MULTILINE)
        if match:
            reasoning = match.group(0).strip()
            # Clean up the reasoning text
            reasoning = re.sub(r'\s+', ' ', reasoning)
            return reasoning[:2000]  # Limit length
        
        return None
    
    @classmethod
    def basic_chunking(cls, document: RawDocument, chunk_size: int = 2000, overlap: int = 200) -> List[ProcessedChunk]:
        """
        Basic text chunking when AI chunking fails.
        
        Args:
            document: Document to chunk
            chunk_size: Target chunk size in characters
            overlap: Overlap between chunks
            
        Returns:
            List of ProcessedChunk objects
        """
        chunks = []
        text = document.content
        
        if len(text) <= chunk_size:
            # Single chunk
            chunk = ProcessedChunk(
                chunk_id=f"{document.id}_chunk_0",
                document_id=document.id,
                content=text,
                chunk_index=0,
                start_char=0,
                end_char=len(text),
                metadata={"chunking_method": "fallback_basic"}
            )
            chunks.append(chunk)
            return chunks
        
        # Multiple chunks with overlap
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = min(start + chunk_size, len(text))
            
            # Try to break at sentence boundary
            if end < len(text):
                # Look for sentence endings within the last 200 characters
                search_start = max(start, end - 200)
                sentence_breaks = [i for i in range(search_start, end) if text[i] in '.!?']
                
                if sentence_breaks:
                    end = sentence_breaks[-1] + 1
            
            chunk_content = text[start:end].strip()
            
            if chunk_content:
                chunk = ProcessedChunk(
                    chunk_id=f"{document.id}_chunk_{chunk_index}",
                    document_id=document.id,
                    content=chunk_content,
                    chunk_index=chunk_index,
                    start_char=start,
                    end_char=end,
                    metadata={"chunking_method": "fallback_basic"}
                )
                chunks.append(chunk)
                chunk_index += 1
            
            # Move start position with overlap
            start = max(end - overlap, start + chunk_size // 2)
            
            # Safety check to prevent infinite loop
            if start >= len(text):
                break
        
        return chunks
    
    @classmethod
    def extract_financial_amounts(cls, text: str) -> List[str]:
        """Extract financial amounts from text."""
        amounts = []
        
        # Extract amounts in PLN
        zl_matches = re.findall(cls.PATTERNS['amount_zl'], text)
        for amount in zl_matches:
            amounts.append(f"{amount} zł")
        
        # Extract amounts written in words
        word_matches = re.findall(cls.PATTERNS['amount_words'], text, re.IGNORECASE)
        for amount in word_matches:
            amounts.append(amount.strip())
        
        return amounts
    
    @classmethod
    def categorize_document_type(cls, text: str) -> Tuple[DocumentType, float]:
        """
        Attempt to categorize document type based on content.
        
        Args:
            text: Document content
            
        Returns:
            Tuple of (DocumentType, confidence_score)
        """
        text_lower = text.lower()
        
        # Check for Supreme Court indicators
        sn_indicators = ['sąd najwyższy', 'kasacja', 'sygn. akt', 'ssn']
        sn_score = sum(1 for indicator in sn_indicators if indicator in text_lower)
        
        # Check for Civil Code indicators
        kc_indicators = ['kodeks cywilny', 'k.c.', 'art.', 'prawo cywilne']
        kc_score = sum(1 for indicator in kc_indicators if indicator in text_lower)
        
        # Check for Civil Procedure indicators
        kpc_indicators = ['kodeks postępowania cywilnego', 'k.p.c.', 'postępowanie cywilne']
        kpc_score = sum(1 for indicator in kpc_indicators if indicator in text_lower)
        
        # Determine most likely type
        if sn_score >= 2:
            return DocumentType.SUPREME_COURT, min(sn_score * 0.25, 0.8)
        elif 'kodeks cywilny' in text_lower or (kc_score >= 2 and kpc_score < 2):
            return DocumentType.CIVIL_CODE, min(kc_score * 0.2, 0.7)
        elif 'kodeks postępowania cywilnego' in text_lower or kpc_score >= 2:
            return DocumentType.CIVIL_PROCEDURE, min(kpc_score * 0.2, 0.7)
        else:
            # Default to Supreme Court if legal indicators present
            legal_score = sn_score + kc_score + kpc_score
            if legal_score > 0:
                return DocumentType.SUPREME_COURT, min(legal_score * 0.1, 0.5)
            else:
                return DocumentType.SUPREME_COURT, 0.1