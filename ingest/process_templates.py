import re
from typing import List, Dict, Optional, Tuple
import pdfplumber
from pathlib import Path
import json
from dataclasses import dataclass
from datetime import datetime
import logging
import sys
import os

# Add app directory to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import init_db_sync, sync_engine
from app.models import Template
from sqlalchemy.orm import sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class DocumentTemplate:
    """Represents a parsed document template"""
    name: str
    template_type: str
    content: str
    variables: List[str]
    metadata: Dict
    description: Optional[str] = None

class TemplateParser:
    """Parser for legal document templates"""
    
    # Common legal document patterns for variable extraction
    VARIABLE_PATTERNS = [
        # Common placeholders: [Name], {Name}, <<Name>>, _Name_
        re.compile(r'\[([^\]]+)\]'),
        re.compile(r'\{([^}]+)\}'),
        re.compile(r'<<([^>]+)>>'),
        re.compile(r'_([^_]+)_'),
        
        # Date patterns
        re.compile(r'(?:dnia?\s+)?(?:__+|\.{3,}|\s{3,})(?:\s*r\.?)?', re.IGNORECASE),
        
        # Amount/number patterns
        re.compile(r'(?:w\s+kwocie|kwotę|wartość|suma)\s+(?:__+|\.{3,})(?:\s*zł)?', re.IGNORECASE),
        
        # Name/address patterns
        re.compile(r'(?:imię\s+i\s+nazwisko|nazwa)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:adres|miejsce\s+zamieszkania)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        
        # Court/case patterns
        re.compile(r'(?:sąd|trybunal)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
        re.compile(r'(?:sygnatura\s+akt|numer\s+sprawy)\s*:?\s*(?:__+|\.{3,})', re.IGNORECASE),
    ]
    
    # Template type mapping based on filename patterns
    TEMPLATE_TYPES = {
        'pozew': ['pozew', 'claim', 'lawsuit'],
        'wniosek': ['wniosek', 'application', 'petition'],
        'apelacja': ['apelacja', 'appeal'],
        'skarga': ['skarga', 'complaint'],
        'sprzeciw': ['sprzeciw', 'objection'],
        'zarzuty': ['zarzuty', 'charges'],
        'zażalenie': ['zażalenie', 'grievance'],
        'pełnomocnictwo': ['pełnomocnictwo', 'power_of_attorney'],
        'umowa': ['umowa', 'contract'],
        'oświadczenie': ['oświadczenie', 'statement'],
    }
    
    def __init__(self):
        self.extracted_variables = set()
    
    def parse_template_pdf(self, pdf_path: str) -> DocumentTemplate:
        """
        Parse a single PDF template
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            DocumentTemplate object
        """
        logger.info(f"Processing template: {pdf_path}")
        
        # Extract text from PDF
        content = self._extract_pdf_text(pdf_path)
        
        # Determine template type and name from filename
        filename = Path(pdf_path).stem
        template_type = self._determine_template_type(filename)
        
        # Extract variables from content
        variables = self._extract_variables(content)
        
        # Generate metadata
        metadata = self._generate_metadata(content, pdf_path)
        
        # Generate description
        description = self._generate_description(template_type, filename)
        
        return DocumentTemplate(
            name=filename,
            template_type=template_type,
            content=content,
            variables=variables,
            metadata=metadata,
            description=description
        )
    
    def _extract_pdf_text(self, pdf_path: str) -> str:
        """Extract text from PDF using pdfplumber"""
        full_text = ""
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
                        
            return full_text.strip()
            
        except Exception as e:
            logger.error(f"Error extracting text from {pdf_path}: {e}")
            return ""
    
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
        """Extract variables based on legal document context"""
        variables = []
        
        # Look for common patterns that indicate variable fields
        common_fields = [
            ('client_name', r'(?:powód|wnioskodawca|strona)\s*:?\s*(?:__+|\.{3,})'),
            ('defendant_name', r'(?:pozwany|uczestnik)\s*:?\s*(?:__+|\.{3,})'),
            ('court_name', r'(?:sąd|do\s+sądu)\s*:?\s*(?:__+|\.{3,})'),
            ('case_number', r'(?:sygnatura|numer\s+sprawy)\s*:?\s*(?:__+|\.{3,})'),
            ('amount', r'(?:kwota|wartość|suma)\s*:?\s*(?:__+|\.{3,})'),
            ('date', r'(?:data|dnia?)\s*:?\s*(?:__+|\.{3,})'),
            ('address', r'(?:adres|zamieszkał[ay])\s*:?\s*(?:__+|\.{3,})'),
        ]
        
        for field_name, pattern in common_fields:
            if re.search(pattern, content, re.IGNORECASE):
                variables.append(field_name)
        
        return variables
    
    def _generate_metadata(self, content: str, pdf_path: str) -> Dict:
        """Generate metadata for the template"""
        return {
            'source_file': str(pdf_path),
            'content_length': len(content),
            'has_signature_field': bool(re.search(r'(?:podpis|signature)', content, re.IGNORECASE)),
            'has_date_field': bool(re.search(r'(?:data|dnia?)', content, re.IGNORECASE)),
            'has_court_field': bool(re.search(r'(?:sąd|court)', content, re.IGNORECASE)),
            'language': 'pl',
            'processed_at': datetime.now().isoformat(),
        }
    
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

class TemplateProcessor:
    """Main processor for handling template ingestion"""
    
    def __init__(self, templates_dir: str = "data/pdfs/templates"):
        self.templates_dir = Path(templates_dir)
        self.parser = TemplateParser()
        self.session = None
    
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
                    
                    # Store in database
                    self._store_template(template)
                    
                    results['processed'] += 1
                    results['templates'].append({
                        'name': template.name,
                        'type': template.template_type,
                        'variables': len(template.variables),
                        'content_length': len(template.content)
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
        """Store template in database"""
        
        # Check if template already exists
        existing = self.session.query(Template).filter_by(name=template.name).first()
        
        if existing:
            logger.info(f"Updating existing template: {template.name}")
            existing.template_type = template.template_type
            existing.description = template.description
            existing.content = template.content
            existing.variables = template.variables
            existing.updated_at = datetime.now()
        else:
            logger.info(f"Creating new template: {template.name}")
            db_template = Template(
                template_type=template.template_type,
                name=template.name,
                description=template.description,
                content=template.content,
                variables=template.variables
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
        """List all available templates"""
        Session = sessionmaker(bind=sync_engine)
        session = Session()
        
        try:
            templates = session.query(Template).all()
            return [
                {
                    'id': t.id,
                    'name': t.name,
                    'type': t.template_type,
                    'description': t.description,
                    'variables': t.variables,
                    'usage_count': t.usage_count,
                    'last_used': t.last_used.isoformat() if t.last_used else None
                }
                for t in templates
            ]
        finally:
            session.close()

def main():
    """Main function to run template processing"""
    processor = TemplateProcessor()
    results = processor.process_all_templates()
    
    # Print summary
    print(f"\n{'='*50}")
    print("TEMPLATE PROCESSING SUMMARY")
    print(f"{'='*50}")
    print(f"Processed: {results['processed']}")
    print(f"Failed: {results['failed']}")
    
    if results['templates']:
        print(f"\nSuccessfully processed templates:")
        for template in results['templates']:
            print(f"  - {template['name']} ({template['type']}) - {template['variables']} variables")
    
    if results['errors']:
        print(f"\nErrors:")
        for error in results['errors']:
            print(f"  - {error['file']}: {error['error']}")
    
    return results

if __name__ == "__main__":
    main()