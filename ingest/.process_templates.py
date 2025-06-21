import re
from typing import List, Dict, Optional, Tuple, Any
import pdfplumber
from pathlib import Path
import json
from dataclasses import dataclass
from datetime import datetime
import logging
import sys
import os
import numpy as np
from sentence_transformers import SentenceTransformer
import hashlib
try:
    from PyPDF2 import PdfReader
    from PyPDF2.generic import DictionaryObject
except ImportError:
    try:
        from pypdf import PdfReader
        DictionaryObject = None
    except ImportError:
        PdfReader = None
        DictionaryObject = None
        logging.warning("PyPDF2/pypdf not available - AcroForm support disabled")

# Add app directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import init_db_sync, sync_engine
from app.models import Template
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize sentence transformer for template embeddings
try:
    embedder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
    logger.info("Loaded SentenceTransformer model for template embeddings")
except Exception as e:
    embedder = None
    logger.warning(f"Could not load SentenceTransformer: {e} - continuing without embeddings")

@dataclass
class DocumentTemplate:
    """Represents a parsed document template"""
    name: str
    template_type: str
    content: str
    variables: List[str]
    metadata: Dict
    description: Optional[str] = None
    form_fields: Optional[Dict[str, Any]] = None
    embeddings: Optional[List[float]] = None
    quality_score: Optional[float] = None
    structure_analysis: Optional[Dict[str, Any]] = None

class TemplateParser:
    """Parser for legal document templates"""
    
    # Enhanced legal document patterns for variable extraction
    VARIABLE_PATTERNS = [
        # Common placeholders: [Name], {Name}, <<Name>>, _Name_
        re.compile(r'\[([^\]]+)\]'),
        re.compile(r'\{([^}]+)\}'),
        re.compile(r'<<([^>]+)>>'),
        re.compile(r'_([^_]{2,})_'),  # At least 2 chars
        
        # Date patterns - enhanced for Polish legal docs
        re.compile(r'(?:dnia?\s+)?(?:__+|\.{3,}|\s{3,})(?:\s*r\.?)?', re.IGNORECASE),
        re.compile(r'\d{2}\.\d{2}\.\d{4}', re.IGNORECASE),  # DD.MM.YYYY
        
        # Amount/number patterns - enhanced
        re.compile(r'(?:w\s+kwocie|kwotę|wartość|suma)\s+(?:__+|\.{3,})(?:\s*(?:zł|PLN))?', re.IGNORECASE),
        re.compile(r'\d+\s*(?:zł|PLN)', re.IGNORECASE),
        
        # Name/address patterns - enhanced for Polish
        re.compile(r'(?:imię\s+i\s+nazwisko|nazwa)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:adres|miejsce\s+zamieszkania|zamieszkały)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:PESEL|NIP)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        
        # Court/case patterns - enhanced
        re.compile(r'(?:sąd|trybunal)\s*(?:rejonowy|okręgowy|wojewódzki)?\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:sygnatura\s+akt|numer\s+sprawy|sygn\.)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        
        # Legal proceeding patterns
        re.compile(r'(?:powód|wnioskodawca|strona)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:pozwany|uczestnik|druga\s+strona)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:przedmiot\s+sporu|wartość\s+przedmiotu)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        
        # Signature patterns
        re.compile(r'(?:podpis|signature)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
    ]
    
    # Enhanced template type mapping with Polish legal specificity
    TEMPLATE_TYPES = {
        'pozew': ['pozew', 'claim', 'lawsuit', 'pozew o zapłatę', 'pozew o rozwód', 'pozew o separację'],
        'wniosek': ['wniosek', 'application', 'petition', 'wniosek o rejestrację', 'wniosek o separację'],
        'apelacja': ['apelacja', 'appeal', 'środek odwoławczy'],
        'skarga': ['skarga', 'complaint', 'skarga na orzeczenie', 'skarga o wznowienie'],
        'sprzeciw': ['sprzeciw', 'objection', 'sprzeciw od nakazu', 'sprzeciw od wyroku'],
        'zarzuty': ['zarzuty', 'charges', 'zarzuty od nakazu'],
        'zażalenie': ['zażalenie', 'grievance'],
        'pełnomocnictwo': ['pełnomocnictwo', 'power_of_attorney', 'pełnomocnictwo procesowe'],
        'umowa': ['umowa', 'contract'],
        'oświadczenie': ['oświadczenie', 'statement'],
        'wezwanie': ['wezwanie', 'demand', 'wezwanie do zapłaty'],
        'odpowiedź': ['odpowiedź', 'response', 'odpowiedź na pozew'],
        'odwołanie': ['odwołanie', 'revocation'],
        'wniosek_o_ubezwłasnowolnienie': ['wniosek o ubezwłasnowolnienie'],
        'wniosek_o_odroczenie': ['wniosek o odroczenie'],
        'wniosek_o_przerwę': ['wniosek o przerwę'],
    }
    
    def __init__(self):
        self.extracted_variables = set()
        self.form_field_cache = {}
    
    def parse_template_pdf(self, pdf_path: str) -> DocumentTemplate:
        """
        Parse a single PDF template
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            DocumentTemplate object
        """
        logger.info(f"Processing template: {pdf_path}")
        
        # Extract text and form fields from PDF
        content, extraction_data = self._extract_pdf_text(pdf_path)
        form_fields = extraction_data.get('form_fields', {})
        pdf_metadata = extraction_data.get('metadata', {})
        
        # Determine template type and name from filename
        filename = Path(pdf_path).stem
        template_type = self._determine_template_type(filename)
        
        # Extract variables from content
        variables = self._extract_variables(content)
        
        # Generate metadata including PDF extraction info
        metadata = self._generate_metadata(content, pdf_path, pdf_metadata)
        
        # Generate embeddings if available
        embeddings = self._generate_embeddings(content)
        
        # Analyze document structure
        structure_analysis = self._analyze_document_structure(content)
        
        # Calculate quality score
        quality_score = self._calculate_quality_score(content, variables, form_fields)
        
        # Generate description
        description = self._generate_description(template_type, filename)
        
        return DocumentTemplate(
            name=filename,
            template_type=template_type,
            content=content,
            variables=variables,
            metadata=metadata,
            description=description,
            form_fields=form_fields,
            embeddings=embeddings,
            quality_score=quality_score,
            structure_analysis=structure_analysis
        )
    
    def _extract_pdf_text(self, pdf_path: str) -> Tuple[str, Dict[str, Any]]:
        """Extract text and form fields from PDF using multiple methods"""
        full_text = ""
        form_fields = {}
        extraction_metadata = {
            'has_acroform': False,
            'field_count': 0,
            'pages': 0,
            'extraction_method': 'pdfplumber'
        }
        
        try:
            # First, try to extract AcroForm fields if PyPDF2 is available
            if PdfReader is not None:
                form_fields, acroform_metadata = self._extract_acroform_fields(pdf_path)
                extraction_metadata.update(acroform_metadata)
            
            # Extract text using pdfplumber with enhanced settings
            with pdfplumber.open(pdf_path) as pdf:
                extraction_metadata['pages'] = len(pdf.pages)
                
                for page_num, page in enumerate(pdf.pages):
                    # Extract text with better settings for forms
                    page_text = page.extract_text(
                        x_tolerance=3,
                        y_tolerance=3,
                        layout=True,
                        x_density=7.25,
                        y_density=13
                    )
                    
                    if page_text:
                        full_text += f"\n--- PAGE {page_num + 1} ---\n{page_text}\n"
                        
                    # Also try to extract tables if present
                    tables = page.extract_tables()
                    if tables:
                        for table_idx, table in enumerate(tables):
                            full_text += f"\n--- TABLE {table_idx + 1} ON PAGE {page_num + 1} ---\n"
                            for row in table:
                                if row:
                                    full_text += "\t".join([str(cell) if cell else "" for cell in row]) + "\n"
                        
            return full_text.strip(), {'form_fields': form_fields, 'metadata': extraction_metadata}
            
        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path}: {e}")
            return "", {'form_fields': {}, 'metadata': extraction_metadata}
    
    def _extract_acroform_fields(self, pdf_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Extract AcroForm fields from PDF if available"""
        form_fields = {}
        metadata = {'has_acroform': False, 'field_count': 0}
        
        try:
            reader = PdfReader(pdf_path)
            # Try different methods to get form fields depending on PyPDF2 version
            try:
                fields = reader.get_form_text_fields()
            except AttributeError:
                # Older version or different implementation
                try:
                    if hasattr(reader, 'get_fields'):
                        fields = reader.get_fields() or {}
                    else:
                        fields = {}
                except:
                    fields = {}
            
            if fields:
                metadata['has_acroform'] = True
                form_fields.update(fields)
                metadata['field_count'] = len(fields)
                logger.info(f"Extracted {len(fields)} AcroForm fields from {pdf_path}")
                
        except Exception as e:
            logger.debug(f"Could not extract AcroForm fields from {pdf_path}: {e}")
            
        return form_fields, metadata
    
    def _determine_template_type(self, filename: str) -> str:
        """Determine template type from filename"""
        filename_lower = filename.lower()
        
        for template_type, keywords in self.TEMPLATE_TYPES.items():
            if any(keyword in filename_lower for keyword in keywords):
                return template_type
        
        # Default type based on first word
        first_word = filename.split()[0].lower() if filename.split() else 'other'
        return first_word
    
    def _extract_variables(self, content: str) -> List[str]:
        """Extract template variables from content"""
        variables = set()
        
        # Extract explicit placeholders
        for pattern in self.VARIABLE_PATTERNS[:4]:  # First 4 are explicit placeholders
            matches = pattern.findall(content)
            for match in matches:
                if len(match.strip()) > 1:  # Ignore single characters
                    variables.add(match.strip())
        
        # Extract common legal document fields by context
        variables.update(self._extract_contextual_variables(content))
        
        return sorted(list(variables))
    
    def _extract_contextual_variables(self, content: str) -> List[str]:
        """Extract variables based on legal document context with enhanced patterns"""
        variables = []
        
        # Enhanced patterns for Polish legal documents
        common_fields = [
            # Basic party information
            ('plaintiff_name', r'(?:powód|wnioskodawca|strona\s+powodowa)\s*:?\s*(?:__+|\.{3,})'),
            ('defendant_name', r'(?:pozwany|uczestnik|strona\s+pozwana)\s*:?\s*(?:__+|\.{3,})'),
            ('client_name', r'(?:klient|zleceniodawca|reprezentowany)\s*:?\s*(?:__+|\.{3,})'),
            
            # Court and case information
            ('court_name', r'(?:sąd|do\s+sądu|trybunal)\s*(?:rejonowy|okręgowy)?\s*(?:w|we)?\s*(?:__+|\.{3,})'),
            ('court_division', r'(?:wydział)\s*(?:cywilny|karny|rodzinny)?\s*:?\s*(?:__+|\.{3,})'),
            ('case_number', r'(?:sygnatura|numer\s+sprawy|sygn\.)\s*:?\s*(?:__+|\.{3,})'),
            ('case_type', r'(?:rodzaj\s+sprawy|typ\s+postepowania)\s*:?\s*(?:__+|\.{3,})'),
            
            # Financial information
            ('amount', r'(?:kwota|wartość|suma|zadłużenie)\s*(?:przedmiotu\s+sporu)?\s*:?\s*(?:__+|\.{3,})'),
            ('currency', r'(?:waluta)\s*:?\s*(?:__+|\.{3,})'),
            ('interest_rate', r'(?:odsetki|oprocentowanie)\s*:?\s*(?:__+|\.{3,})'),
            
            # Dates
            ('date', r'(?:data|dnia?)\s*:?\s*(?:__+|\.{3,})'),
            ('due_date', r'(?:termin\s+płatności|data\s+wymagalności)\s*:?\s*(?:__+|\.{3,})'),
            ('filing_date', r'(?:data\s+złożenia|data\s+wniesienia)\s*:?\s*(?:__+|\.{3,})'),
            
            # Personal information
            ('address', r'(?:adres|miejsce\s+zamieszkania|zamieszkał[ay])\s*:?\s*(?:__+|\.{3,})'),
            ('pesel', r'(?:PESEL)\s*:?\s*(?:__+|\.{3,})'),
            ('nip', r'(?:NIP|numer\s+identyfikacji\s+podatkowej)\s*:?\s*(?:__+|\.{3,})'),
            ('phone', r'(?:telefon|nr\s+tel|tel\.)\s*:?\s*(?:__+|\.{3,})'),
            ('email', r'(?:email|e-mail|adres\s+email)\s*:?\s*(?:__+|\.{3,})'),
            
            # Legal specifics
            ('legal_basis', r'(?:podstawa\s+prawna|na\s+podstawie)\s*:?\s*(?:__+|\.{3,})'),
            ('relief_sought', r'(?:wnoszę\s+o|żądam|petitum)\s*:?\s*(?:__+|\.{3,})'),
            ('evidence', r'(?:dowody|załączniki)\s*:?\s*(?:__+|\.{3,})'),
            
            # Signature and location
            ('signature', r'(?:podpis|signature)\s*:?\s*(?:__+|\.{3,})'),
            ('place', r'(?:miejsce|miasto)\s*:?\s*(?:__+|\.{3,})'),
        ]
        
        for field_name, pattern in common_fields:
            if re.search(pattern, content, re.IGNORECASE):
                variables.append(field_name)
        
        return variables
    
    def _generate_metadata(self, content: str, pdf_path: str, pdf_metadata: Dict = None) -> Dict:
        """Generate comprehensive metadata for the template"""
        base_metadata = {
            'source_file': str(pdf_path),
            'file_size': os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0,
            'content_length': len(content),
            'word_count': len(content.split()),
            'language': 'pl',
            'processed_at': datetime.now().isoformat(),
            'content_hash': hashlib.md5(content.encode('utf-8')).hexdigest(),
        }
        
        # Add PDF extraction metadata
        if pdf_metadata:
            base_metadata.update(pdf_metadata)
        
        # Enhanced field detection
        field_analysis = {
            'has_signature_field': bool(re.search(r'(?:podpis|signature)', content, re.IGNORECASE)),
            'has_date_field': bool(re.search(r'(?:data|dnia?)', content, re.IGNORECASE)),
            'has_court_field': bool(re.search(r'(?:sąd|court|trybunal)', content, re.IGNORECASE)),
            'has_amount_field': bool(re.search(r'(?:kwota|suma|wartość)', content, re.IGNORECASE)),
            'has_party_fields': bool(re.search(r'(?:powód|pozwany|strona)', content, re.IGNORECASE)),
            'has_address_field': bool(re.search(r'(?:adres|zamieszkania)', content, re.IGNORECASE)),
            'has_case_number': bool(re.search(r'(?:sygnatura|numer\s+sprawy)', content, re.IGNORECASE)),
        }
        
        # Document complexity analysis
        complexity_analysis = {
            'paragraph_count': len([p for p in content.split('\n\n') if p.strip()]),
            'sentence_count': len([s for s in content.split('.') if s.strip()]),
            'legal_references': len(re.findall(r'(?:art\.|\u00a7|ustawa|kodeks)', content, re.IGNORECASE)),
            'blank_fields_count': len(re.findall(r'(?:__+|\.{3,})', content)),
        }
        
        base_metadata.update(field_analysis)
        base_metadata.update(complexity_analysis)
        
        return base_metadata
    
    def validate_template(self, template: DocumentTemplate) -> Dict[str, Any]:
        """Validate template quality and completeness"""
        validation = {
            'is_valid': True,
            'warnings': [],
            'errors': [],
            'score': template.quality_score or 0.0
        }
        
        # Check content length
        if len(template.content) < 100:
            validation['warnings'].append("Template content is very short")
        elif len(template.content) > 50000:
            validation['warnings'].append("Template content is very long")
        
        # Check for variables
        if not template.variables:
            validation['warnings'].append("No variables detected in template")
        elif len(template.variables) > 50:
            validation['warnings'].append("Unusually high number of variables detected")
        
        # Check for Polish legal document structure
        required_elements = [
            (r'(?:sąd|trybunal)', 'Missing court reference'),
            (r'(?:pozew|wniosek|skarga)', 'Missing document type indicator'),
        ]
        
        for pattern, error_msg in required_elements:
            if not re.search(pattern, template.content, re.IGNORECASE):
                validation['warnings'].append(error_msg)
        
        # Check quality score
        if template.quality_score and template.quality_score < 0.3:
            validation['warnings'].append("Low quality score - template may need review")
        
        # Set overall validity
        validation['is_valid'] = len(validation['errors']) == 0
        
        return validation
    
    def _generate_description(self, template_type: str, filename: str) -> str:
        """Generate a description for the template"""
        type_descriptions = {
            'pozew': 'Szablon pozwu - document służący do wniesienia sprawy do sądu',
            'wniosek': 'Szablon wniosku - dokument służący do złożenia wniosku w postępowaniu sądowym',
            'apelacja': 'Szablon apelacji - dokument służący do odwołania się od wyroku',
            'skarga': 'Szablon skargi - dokument służący do wniesienia skargi',
            'sprzeciw': 'Szablon sprzeciwu - dokument służący do wniesienia sprzeciwu',
            'pełnomocnictwo': 'Szablon pełnomocnictwa - dokument upoważniający do reprezentacji',
        }
        
        base_desc = type_descriptions.get(template_type, f'Szablon dokumentu typu: {template_type}')
        return f"{base_desc} - {filename}"
    
    def _generate_embeddings(self, content: str) -> Optional[List[float]]:
        """Generate embeddings for template content for semantic search"""
        if embedder is None:
            return None
            
        try:
            # Create a summary of the template for embedding
            summary_text = self._create_embedding_text(content)
            embeddings = embedder.encode(summary_text).tolist()
            logger.debug(f"Generated embeddings of length {len(embeddings)}")
            return embeddings
        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            return None
    
    def _create_embedding_text(self, content: str) -> str:
        """Create optimized text for embedding generation"""
        # Extract key phrases and structure for embedding
        lines = content.split('\n')
        
        # Get title/header (usually first few non-empty lines)
        title_lines = []
        for line in lines[:10]:
            if line.strip() and not re.match(r'^[-=_]+$', line.strip()):
                title_lines.append(line.strip())
                if len(title_lines) >= 3:
                    break
        
        # Extract key legal phrases
        legal_phrases = re.findall(r'(?:wnoszę\s+o|na\s+podstawie|zgodnie\s+z|w\s+trybie)[^.]*', content, re.IGNORECASE)[:5]
        
        # Combine for embedding
        embedding_text = ' '.join(title_lines)
        if legal_phrases:
            embedding_text += ' ' + ' '.join(legal_phrases)
            
        return embedding_text[:500]  # Limit length
    
    def _analyze_document_structure(self, content: str) -> Dict[str, Any]:
        """Analyze the structure of the legal document"""
        lines = [line.strip() for line in content.split('\n') if line.strip()]
        
        structure = {
            'sections': [],
            'has_header': False,
            'has_footer': False,
            'enumerated_items': 0,
            'legal_citations': 0,
            'structure_quality': 'good'
        }
        
        # Detect sections/headers (all caps lines, numbered sections, etc.)
        for i, line in enumerate(lines):
            if len(line) > 5:
                # All caps might be a header
                if line.isupper() and not re.search(r'[0-9]{2,}', line):
                    structure['sections'].append({
                        'line_number': i,
                        'text': line,
                        'type': 'header'
                    })
                
                # Numbered items (1., 2., etc.)
                if re.match(r'^\d+\.\s', line):
                    structure['enumerated_items'] += 1
        
        # Detect header (court name, case info in first 20% of document)
        header_cutoff = len(lines) // 5
        court_pattern = r'(?:sąd|trybunal)'
        if any(re.search(court_pattern, line, re.IGNORECASE) for line in lines[:header_cutoff]):
            structure['has_header'] = True
        
        # Detect footer (signature, date in last 20% of document)
        footer_cutoff = len(lines) - (len(lines) // 5)
        signature_pattern = r'(?:podpis|data|miejscowość)'
        if any(re.search(signature_pattern, line, re.IGNORECASE) for line in lines[footer_cutoff:]):
            structure['has_footer'] = True
        
        # Count legal citations
        structure['legal_citations'] = len(re.findall(r'(?:art\.|\u00a7|ustawa|kodeks)', content, re.IGNORECASE))
        
        # Assess structure quality
        quality_score = 0
        if structure['has_header']: quality_score += 1
        if structure['has_footer']: quality_score += 1
        if structure['enumerated_items'] > 0: quality_score += 1
        if len(structure['sections']) > 0: quality_score += 1
        
        if quality_score >= 3:
            structure['structure_quality'] = 'excellent'
        elif quality_score >= 2:
            structure['structure_quality'] = 'good'
        elif quality_score >= 1:
            structure['structure_quality'] = 'fair'
        else:
            structure['structure_quality'] = 'poor'
        
        return structure
    
    def _calculate_quality_score(self, content: str, variables: List[str], form_fields: Dict) -> float:
        """Calculate a quality score for the template (0.0 to 1.0)"""
        score = 0.0
        max_score = 0.0
        
        # Content length (reasonable template should have substantive content)
        max_score += 0.2
        if 500 <= len(content) <= 10000:
            score += 0.2
        elif 200 <= len(content) < 500 or 10000 < len(content) <= 20000:
            score += 0.1
        
        # Variable extraction (good templates have identifiable variables)
        max_score += 0.2
        if len(variables) >= 5:
            score += 0.2
        elif len(variables) >= 3:
            score += 0.15
        elif len(variables) >= 1:
            score += 0.1
        
        # Form fields (AcroForm templates are higher quality)
        max_score += 0.15
        if len(form_fields) > 0:
            score += 0.15
        
        # Legal structure indicators
        max_score += 0.15
        legal_indicators = [
            r'(?:wnoszę\s+o|w\s+sprawie)',  # Formal request language
            r'(?:na\s+podstawie|zgodnie\s+z)',  # Legal basis
            r'(?:powód|pozwany|sąd)',  # Legal parties
            r'(?:art\.|\u00a7|ustawa)',  # Legal references
        ]
        found_indicators = sum(1 for pattern in legal_indicators if re.search(pattern, content, re.IGNORECASE))
        score += (found_indicators / len(legal_indicators)) * 0.15
        
        # Polish legal language
        max_score += 0.1
        polish_legal_terms = [
            r'sygnatura', r'pozew', r'wniosek', r'załączniki', r'uzasadnienie'
        ]
        found_terms = sum(1 for term in polish_legal_terms if re.search(term, content, re.IGNORECASE))
        score += min(found_terms / len(polish_legal_terms), 1.0) * 0.1
        
        # Text quality (no excessive repetition, reasonable sentence structure)
        max_score += 0.2
        sentences = [s.strip() for s in content.split('.') if s.strip()]
        if len(sentences) > 3:
            avg_sentence_length = sum(len(s.split()) for s in sentences) / len(sentences)
            if 8 <= avg_sentence_length <= 25:  # Reasonable sentence length
                score += 0.1
            
            # Check for repetitive content
            unique_sentences = len(set(sentences))
            repetition_ratio = unique_sentences / len(sentences) if sentences else 0
            if repetition_ratio > 0.8:
                score += 0.1
        
        return min(score / max_score, 1.0) if max_score > 0 else 0.0

class TemplateProcessor:
    """Main processor for handling template ingestion with intelligent field detection"""
    
    def __init__(self, templates_dir: str = "data/pdfs/templates"):
        self.templates_dir = Path(templates_dir)
        self.parser = TemplateParser()
        self.session = None
        self.field_detector = IntelligentFieldDetector()
        
    def detect_template_fields(self, template: DocumentTemplate) -> DocumentTemplate:
        """Use intelligent field detection to enhance template analysis"""
        enhanced_fields = self.field_detector.detect_fields(
            template.content, 
            template.form_fields
        )
        
        # Merge detected fields with existing variables
        all_variables = set(template.variables)
        all_variables.update(enhanced_fields.get('detected_variables', []))
        template.variables = sorted(list(all_variables))
        
        # Update metadata with field detection results
        template.metadata.update({
            'intelligent_fields': enhanced_fields,
            'field_detection_confidence': enhanced_fields.get('confidence', 0.0)
        })
        
        return template

class IntelligentFieldDetector:
    """Intelligent field detection using pattern matching and context analysis"""
    
    def __init__(self):
        # Enhanced field patterns with confidence scores
        self.field_patterns = {
            'court_info': {
                'patterns': [
                    (r'(sąd\s+rejonowy\s+(?:w|we)\s+([\w\s]+))', 0.9),
                    (r'(sąd\s+okręgowy\s+(?:w|we)\s+([\w\s]+))', 0.9),
                    (r'(wydział\s+(\w+)\s+cywilny)', 0.8),
                ],
                'variables': ['court_name', 'court_location', 'court_division']
            },
            'party_info': {
                'patterns': [
                    (r'powód:\s*([^\n]+)', 0.9),
                    (r'pozwany:\s*([^\n]+)', 0.9),
                    (r'wnioskodawca:\s*([^\n]+)', 0.85),
                    (r'uczestnik:\s*([^\n]+)', 0.8),
                ],
                'variables': ['plaintiff_name', 'defendant_name', 'applicant_name', 'participant_name']
            },
            'financial_info': {
                'patterns': [
                    (r'(?:kwota|suma|wartość)\s*(?:przedmiotu\s+sporu)?[:\s]*(\d+(?:[.,]\d+)?)\s*zł', 0.9),
                    (r'zadłużenie[:\s]*(\d+(?:[.,]\d+)?)\s*zł', 0.85),
                    (r'odsetki[:\s]*([\d.,]+)%', 0.8),
                ],
                'variables': ['amount', 'debt_amount', 'interest_rate']
            },
            'dates': {
                'patterns': [
                    (r'(\d{1,2}[./]\d{1,2}[./]\d{4})', 0.9),
                    (r'dnia\s+(\d{1,2})\s+(\w+)\s+(\d{4})', 0.85),
                    (r'termin\s+płatności[:\s]*([^\n]+)', 0.8),
                ],
                'variables': ['date', 'payment_date', 'due_date']
            },
            'identification': {
                'patterns': [
                    (r'PESEL[:\s]*(\d{11})', 0.95),
                    (r'NIP[:\s]*(\d{10})', 0.95),
                    (r'(?:sygnatura|sygn\.)\s*akt[:\s]*([^\n]+)', 0.9),
                ],
                'variables': ['pesel', 'nip', 'case_signature']
            }
        }
    
    def detect_fields(self, content: str, form_fields: Dict = None) -> Dict[str, Any]:
        """Detect fields using intelligent pattern matching"""
        detected = {
            'detected_variables': [],
            'field_values': {},
            'confidence_scores': {},
            'pattern_matches': {},
            'confidence': 0.0
        }
        
        total_confidence = 0.0
        match_count = 0
        
        # Process each field category
        for category, category_data in self.field_patterns.items():
            patterns = category_data['patterns']
            variables = category_data['variables']
            
            category_matches = []
            
            for pattern, confidence in patterns:
                matches = re.finditer(pattern, content, re.IGNORECASE | re.MULTILINE)
                for match in matches:
                    match_info = {
                        'pattern': pattern,
                        'match': match.group(),
                        'groups': match.groups(),
                        'confidence': confidence,
                        'position': match.span()
                    }
                    category_matches.append(match_info)
                    
                    # Extract variable name from context
                    var_name = self._infer_variable_name(match.group(), variables)
                    if var_name:
                        detected['detected_variables'].append(var_name)
                        detected['field_values'][var_name] = match.groups()[0] if match.groups() else match.group()
                        detected['confidence_scores'][var_name] = confidence
                        
                        total_confidence += confidence
                        match_count += 1
            
            if category_matches:
                detected['pattern_matches'][category] = category_matches
        
        # Add form field variables if available
        if form_fields:
            for field_name, field_value in form_fields.items():
                var_name = self._normalize_field_name(field_name)
                detected['detected_variables'].append(var_name)
                detected['field_values'][var_name] = field_value
                detected['confidence_scores'][var_name] = 1.0  # Form fields are certain
                total_confidence += 1.0
                match_count += 1
        
        # Calculate overall confidence
        detected['confidence'] = (total_confidence / match_count) if match_count > 0 else 0.0
        detected['detected_variables'] = list(set(detected['detected_variables']))  # Remove duplicates
        
        return detected
    
    def _infer_variable_name(self, match_text: str, possible_variables: List[str]) -> Optional[str]:
        """Infer the most likely variable name from match text and context"""
        match_lower = match_text.lower()
        
        # Simple heuristics for variable name inference
        for var in possible_variables:
            if any(keyword in match_lower for keyword in var.split('_')):
                return var
        
        # Return first variable as fallback
        return possible_variables[0] if possible_variables else None
    
    def _normalize_field_name(self, field_name: str) -> str:
        """Normalize form field name to standard variable name"""
        # Convert camelCase and spaces to snake_case
        name = re.sub(r'([A-Z])', r'_\1', field_name).lower()
        name = re.sub(r'[\s-]+', '_', name)
        name = re.sub(r'_+', '_', name).strip('_')
        return name
    
    def process_all_templates(self) -> Dict:
        """Process all PDF templates in the templates directory"""
        
        # Initialize database
        init_db_sync()
        Session = sessionmaker(bind=sync_engine)
        self.session = Session()
        
        try:
            # Find all PDF files
            pdf_files = list(self.templates_dir.glob("*.pdf"))
            logger.info(f"Found {len(pdf_files)} PDF templates to process")
            
            results = {
                'processed': 0,
                'failed': 0,
                'templates': [],
                'errors': []
            }
            
            for pdf_path in pdf_files:
                try:
                    # Parse template
                    template = self.parser.parse_template_pdf(str(pdf_path))
                    
                    # Apply intelligent field detection
                    template = self.detect_template_fields(template)
                    
                    # Validate template
                    validation = self.parser.validate_template(template)
                    
                    # Store in database
                    self._store_template(template)
                    
                    results['processed'] += 1
                    results['templates'].append({
                        'name': template.name,
                        'type': template.template_type,
                        'variables': len(template.variables),
                        'content_length': len(template.content),
                        'quality_score': template.quality_score,
                        'has_form_fields': bool(template.form_fields),
                        'structure_quality': template.structure_analysis.get('structure_quality', 'unknown') if template.structure_analysis else 'unknown',
                        'validation': validation,
                        'form_field_count': len(template.form_fields) if template.form_fields else 0
                    })
                    
                    logger.info(f"Successfully processed: {template.name}")
                    
                except Exception as e:
                    logger.error(f"Failed to process {pdf_path}: {e}")
                    results['failed'] += 1
                    results['errors'].append({
                        'file': str(pdf_path),
                        'error': str(e)
                    })
            
            self.session.commit()
            logger.info(f"Processing complete: {results['processed']} succeeded, {results['failed']} failed")
            
            return results
            
        except Exception as e:
            if self.session:
                self.session.rollback()
            raise
        finally:
            if self.session:
                self.session.close()
    
    def _store_template(self, template: DocumentTemplate):
        """Store enhanced template in database with all new fields"""
        
        # Prepare metadata for storage (merge all metadata)
        full_metadata = template.metadata.copy()
        if template.form_fields:
            full_metadata['form_fields'] = template.form_fields
        if template.structure_analysis:
            full_metadata['structure_analysis'] = template.structure_analysis
        if template.quality_score is not None:
            full_metadata['quality_score'] = template.quality_score
        if template.embeddings:
            full_metadata['has_embeddings'] = True
            full_metadata['embedding_dimensions'] = len(template.embeddings)
        
        # Check if template already exists
        existing = self.session.query(Template).filter_by(name=template.name).first()
        
        if existing:
            logger.info(f"Updating existing template: {template.name} (quality: {template.quality_score:.2f})")
            existing.template_type = template.template_type
            existing.description = template.description
            existing.content = template.content
            existing.variables = template.variables
            existing.updated_at = datetime.now()
            # Note: Template model doesn't have metadata field, but we could extend it
            # For now, store key info in variables as structured data
            if template.form_fields:
                # Include form field names in variables for backward compatibility
                form_field_vars = [f"form_field:{name}" for name in template.form_fields.keys()]
                existing.variables = list(set(existing.variables + form_field_vars))
        else:
            logger.info(f"Creating new template: {template.name} (quality: {template.quality_score:.2f})")
            # Prepare variables including form fields
            all_variables = template.variables.copy()
            if template.form_fields:
                form_field_vars = [f"form_field:{name}" for name in template.form_fields.keys()]
                all_variables.extend(form_field_vars)
            
            db_template = Template(
                template_type=template.template_type,
                name=template.name,
                description=template.description,
                content=template.content,
                variables=list(set(all_variables))  # Remove duplicates
            )
            self.session.add(db_template)
    
    def get_template_by_type(self, template_type: str) -> Optional[Template]:
        """Get a template by type from database"""
        Session = sessionmaker(bind=sync_engine)
        session = Session()
        
        try:
            template = session.query(Template).filter_by(template_type=template_type).first()
            return template
        finally:
            session.close()
    
    def list_available_templates(self) -> List[Dict]:
        """List all available templates with enhanced information"""
        Session = sessionmaker(bind=sync_engine)
        session = Session()
        
        try:
            templates = session.query(Template).all()
            result = []
            
            for t in templates:
                template_info = {
                    'id': t.id,
                    'name': t.name,
                    'type': t.template_type,
                    'description': t.description,
                    'variables': t.variables,
                    'usage_count': t.usage_count,
                    'last_used': t.last_used.isoformat() if t.last_used else None,
                    'variable_count': len(t.variables) if t.variables else 0,
                    'content_length': len(t.content) if t.content else 0
                }
                
                # Extract additional info from variables
                if t.variables:
                    form_fields = [v for v in t.variables if v.startswith('form_field:')]
                    regular_vars = [v for v in t.variables if not v.startswith('form_field:')]
                    template_info['form_field_count'] = len(form_fields)
                    template_info['regular_variable_count'] = len(regular_vars)
                    template_info['has_form_fields'] = len(form_fields) > 0
                else:
                    template_info['form_field_count'] = 0
                    template_info['regular_variable_count'] = 0
                    template_info['has_form_fields'] = False
                
                result.append(template_info)
            
            # Sort by usage count and quality (inferred from variable count)
            result.sort(key=lambda x: (x['usage_count'] or 0, x['variable_count']), reverse=True)
            return result
        finally:
            session.close()
    
    def find_best_template(self, document_type: str, required_fields: List[str] = None) -> Optional[Dict]:
        """Find the best matching template for a given document type and requirements"""
        Session = sessionmaker(bind=sync_engine)
        session = Session()
        
        try:
            # Get all templates of the requested type
            candidates = session.query(Template).filter_by(template_type=document_type).all()
            
            if not candidates:
                # Try partial matching on template type
                candidates = session.query(Template).filter(
                    Template.template_type.like(f'%{document_type}%')
                ).all()
            
            if not candidates:
                return None
            
            best_template = None
            best_score = 0.0
            
            for template in candidates:
                score = self._calculate_template_score(template, required_fields)
                if score > best_score:
                    best_score = score
                    best_template = template
            
            if best_template:
                return {
                    'id': best_template.id,
                    'name': best_template.name,
                    'type': best_template.template_type,
                    'description': best_template.description,
                    'content': best_template.content,
                    'variables': best_template.variables,
                    'match_score': best_score,
                    'usage_count': best_template.usage_count
                }
            
            return None
            
        finally:
            session.close()
    
    def _calculate_template_score(self, template: Template, required_fields: List[str] = None) -> float:
        """Calculate matching score for a template"""
        score = 0.0
        
        # Base score from usage count (popular templates are likely better)
        if template.usage_count:
            score += min(template.usage_count * 0.1, 0.3)
        
        # Score from variable richness
        if template.variables:
            var_score = min(len(template.variables) * 0.05, 0.4)
            score += var_score
        
        # Score from required fields matching
        if required_fields and template.variables:
            template_vars = set(template.variables)
            required_set = set(required_fields)
            
            # Direct matches
            direct_matches = len(required_set.intersection(template_vars))
            match_ratio = direct_matches / len(required_set) if required_set else 0
            score += match_ratio * 0.3
            
            # Partial matches (fuzzy matching)
            partial_matches = 0
            for req_field in required_fields:
                for template_var in template.variables:
                    if self._fields_similar(req_field, template_var):
                        partial_matches += 1
                        break
            
            partial_ratio = partial_matches / len(required_fields) if required_fields else 0
            score += partial_ratio * 0.2
        
        return min(score, 1.0)
    
    def _fields_similar(self, field1: str, field2: str) -> bool:
        """Check if two field names are similar"""
        # Simple similarity check
        field1_parts = set(field1.lower().split('_'))
        field2_parts = set(field2.lower().split('_'))
        
        # If they share any meaningful parts
        common_parts = field1_parts.intersection(field2_parts)
        return len(common_parts) > 0 and any(len(part) > 2 for part in common_parts)

def main():
    """Main function to run enhanced template processing"""
    processor = TemplateProcessor()
    results = processor.process_all_templates()
    
    # Print enhanced summary
    print(f"\n{'='*60}")
    print("ENHANCED TEMPLATE PROCESSING SUMMARY")
    print(f"{'='*60}")
    print(f"Processed: {results['processed']}")
    print(f"Failed: {results['failed']}")
    
    if results['templates']:
        print(f"\n{'Template Name':<30} {'Type':<15} {'Vars':<5} {'Quality':<8} {'Length':<8}")
        print("-" * 70)
        for template in results['templates']:
            quality = template.get('quality_score', 0.0)
            length = template.get('content_length', 0)
            print(f"{template['name'][:29]:<30} {template['type']:<15} {template['variables']:<5} {quality:.2f}{'':4} {length:<8}")
    
    if results['errors']:
        print(f"\nErrors ({len(results['errors'])}):") 
        for error in results['errors']:
            print(f"  - {Path(error['file']).name}: {error['error']}")
    
    # Show statistics
    if results['templates']:
        quality_scores = [t.get('quality_score', 0.0) for t in results['templates']]
        avg_quality = sum(quality_scores) / len(quality_scores)
        print(f"\nQuality Statistics:")
        print(f"  Average Quality Score: {avg_quality:.2f}")
        print(f"  High Quality Templates (>0.7): {sum(1 for q in quality_scores if q > 0.7)}")
        print(f"  Medium Quality Templates (0.4-0.7): {sum(1 for q in quality_scores if 0.4 <= q <= 0.7)}")
        print(f"  Low Quality Templates (<0.4): {sum(1 for q in quality_scores if q < 0.4)}")
    
    return results

def search_templates(query: str = None, template_type: str = None, min_quality: float = 0.0) -> List[Dict]:
    """Search templates with filters"""
    processor = TemplateProcessor()
    templates = processor.list_available_templates()
    
    filtered = templates
    
    if template_type:
        filtered = [t for t in filtered if template_type.lower() in t['type'].lower()]
    
    if min_quality > 0.0:
        # Estimate quality from variable count and usage
        filtered = [t for t in filtered if 
                   (t['variable_count'] * 0.1 + (t['usage_count'] or 0) * 0.05) >= min_quality]
    
    if query:
        query_lower = query.lower()
        filtered = [t for t in filtered if 
                   query_lower in t['name'].lower() or 
                   query_lower in (t['description'] or '').lower()]
    
    return filtered

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Template Processor for Polish Legal Documents')
    parser.add_argument('--search', type=str, help='Search templates by name or description')
    parser.add_argument('--type', type=str, help='Filter by template type')
    parser.add_argument('--min-quality', type=float, default=0.0, help='Minimum quality score filter')
    parser.add_argument('--list', action='store_true', help='List all templates')
    parser.add_argument('--process', action='store_true', help='Process all templates')
    parser.add_argument('--check-deps', action='store_true', help='Check dependencies')
    
    args = parser.parse_args()
    
    # Check dependencies if requested
    if args.check_deps:
        if hasattr(sys.modules[__name__], 'check_dependencies'):
            check_dependencies()
        else:
            print("Dependency check function not available")
        sys.exit(0)
    
    if args.list or args.search or args.type or args.min_quality > 0:
        # Search/list mode
        templates = search_templates(args.search, args.type, args.min_quality)
        
        if templates:
            print(f"\nFound {len(templates)} matching templates:")
            print(f"{'Name':<30} {'Type':<15} {'Variables':<10} {'Usage':<8}")
            print("-" * 65)
            for t in templates:
                usage = t['usage_count'] or 0
                print(f"{t['name'][:29]:<30} {t['type']:<15} {t['variable_count']:<10} {usage:<8}")
        else:
            print("No templates found matching criteria.")
    elif args.process:
        # Process mode
        main()
    else:
        # Default: show help
        print("\nEnhanced Template Processor for Polish Legal Documents")
        print("Use --help to see available options")
        print("Use --process to process templates")
        print("Use --list to list processed templates")