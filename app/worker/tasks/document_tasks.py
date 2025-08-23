"""
Celery tasks for document generation operations.
"""
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import json
import uuid
import re

from app.worker.celery_app import celery_app
from app.core.database_manager import DatabaseManager
from app.core.config_service import ConfigService
from app.core.logger_manager import get_logger
from app.core.llm_manager import LLMManager
from app.services.document_generation_service import DocumentGenerationService
from app.services.statute_search_service import StatuteSearchService
from app.services.supreme_court_service import SupremeCourtService

logger = get_logger(__name__)

def run_async(coro):
    """Helper to run async code in sync context."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    name="worker.tasks.document_tasks.generate_legal_document",
    bind=True,
    max_retries=3,
    default_retry_delay=60
)
def generate_legal_document(
    self,
    document_type: str,
    context: Dict[str, Any],
    user_id: str
) -> Dict[str, Any]:
    """
    Generate a legal document based on type and context.
    
    Args:
        document_type: Type of document to generate (pozew, odpowiedz, umowa, etc.)
        context: Context information for document generation
        user_id: ID of the user requesting the document
        
    Returns:
        Generated document content and metadata
    """
    logger.info(f"Generating {document_type} document for user {user_id}")
    
    async def _process():
        config_service = ConfigService()
        db_manager = DatabaseManager(config_service)
        llm_manager = LLMManager(config_service)
        
        try:
            await db_manager.initialize()
            await llm_manager.initialize()
            
            # Initialize services
            statute_search = StatuteSearchService(config_service)
            supreme_court = SupremeCourtService(db_manager, config_service)
            doc_service = DocumentGenerationService(
                db_manager, 
                statute_search, 
                supreme_court
            )
            
            await statute_search.initialize()
            await supreme_court.initialize()
            await doc_service.initialize()
            
            # Generate document based on type
            if document_type == "pozew":
                content = await _generate_pozew(doc_service, context)
            elif document_type == "odpowiedz_na_pozew":
                content = await _generate_response(doc_service, context)
            elif document_type == "umowa":
                content = await _generate_contract(doc_service, context)
            elif document_type == "pismo_procesowe":
                content = await _generate_court_filing(doc_service, context)
            else:
                content = await _generate_generic_document(doc_service, document_type, context)
            
            # Save to database
            document_id = str(uuid.uuid4())
            
            return {
                "status": "success",
                "document_id": document_id,
                "document_type": document_type,
                "content": content,
                "generated_at": datetime.utcnow().isoformat(),
                "word_count": len(content.split()),
                "user_id": user_id
            }
            
        except Exception as e:
            logger.error(f"Error generating document: {e}", exc_info=True)
            raise self.retry(exc=e)
        finally:
            if db_manager:
                await db_manager.shutdown()
            if llm_manager:
                await llm_manager.shutdown()
    
    return run_async(_process())


async def _generate_pozew(service, context: Dict[str, Any]) -> str:
    """Generate a lawsuit document."""
    template = """
    Sąd {court_name}
    w {court_location}
    
    Powód: {plaintiff_name}
    {plaintiff_address}
    
    Pozwany: {defendant_name}
    {defendant_address}
    
    POZEW
    o {claim_type}
    
    Wartość przedmiotu sporu: {claim_amount} zł
    
    Uzasadnienie:
    {claim_justification}
    
    Dowody:
    {evidence_list}
    
    W związku z powyższym wnoszę o:
    {demands}
    
    Załączniki:
    {attachments}
    """
    
    # Fill in the template with context
    return template.format(
        court_name=context.get("court_name", "Rejonowy"),
        court_location=context.get("court_location", "Warszawie"),
        plaintiff_name=context.get("plaintiff_name", ""),
        plaintiff_address=context.get("plaintiff_address", ""),
        defendant_name=context.get("defendant_name", ""),
        defendant_address=context.get("defendant_address", ""),
        claim_type=context.get("claim_type", "zapłatę"),
        claim_amount=context.get("claim_amount", "0"),
        claim_justification=context.get("claim_justification", ""),
        evidence_list=context.get("evidence_list", ""),
        demands=context.get("demands", ""),
        attachments=context.get("attachments", "")
    )


async def _generate_response(service, context: Dict[str, Any]) -> str:
    """Generate a response to lawsuit document."""
    template = """
    Sąd {court_name}
    w {court_location}
    
    Sygnatura akt: {case_number}
    
    Pozwany: {defendant_name}
    
    ODPOWIEDŹ NA POZEW
    
    W odpowiedzi na pozew z dnia {lawsuit_date} wnoszę o:
    
    {response_type}
    
    Uzasadnienie:
    {justification}
    
    Dowody:
    {evidence}
    
    Zarzuty procesowe:
    {procedural_objections}
    """
    
    return template.format(
        court_name=context.get("court_name", ""),
        court_location=context.get("court_location", ""),
        case_number=context.get("case_number", ""),
        defendant_name=context.get("defendant_name", ""),
        lawsuit_date=context.get("lawsuit_date", ""),
        response_type=context.get("response_type", "oddalenie powództwa w całości"),
        justification=context.get("justification", ""),
        evidence=context.get("evidence", ""),
        procedural_objections=context.get("procedural_objections", "")
    )


async def _generate_contract(service, context: Dict[str, Any]) -> str:
    """Generate a contract document."""
    template = """
    UMOWA {contract_type}
    
    zawarta w dniu {date} w {location} pomiędzy:
    
    {party1_name}, {party1_details}
    zwanym dalej "Stroną 1"
    
    a
    
    {party2_name}, {party2_details}
    zwanym dalej "Stroną 2"
    
    §1 Przedmiot umowy
    {subject}
    
    §2 Zobowiązania stron
    {obligations}
    
    §3 Wynagrodzenie
    {payment_terms}
    
    §4 Termin realizacji
    {timeline}
    
    §5 Postanowienia końcowe
    {final_provisions}
    """
    
    return template.format(
        contract_type=context.get("contract_type", ""),
        date=context.get("date", datetime.utcnow().strftime("%Y-%m-%d")),
        location=context.get("location", ""),
        party1_name=context.get("party1_name", ""),
        party1_details=context.get("party1_details", ""),
        party2_name=context.get("party2_name", ""),
        party2_details=context.get("party2_details", ""),
        subject=context.get("subject", ""),
        obligations=context.get("obligations", ""),
        payment_terms=context.get("payment_terms", ""),
        timeline=context.get("timeline", ""),
        final_provisions=context.get("final_provisions", "")
    )


async def _generate_court_filing(service, context: Dict[str, Any]) -> str:
    """Generate a court filing document."""
    template = """
    Sąd {court_name}
    w {court_location}
    
    Sygnatura akt: {case_number}
    
    {party_name}
    {party_role}
    
    PISMO PROCESOWE
    
    {content}
    
    W załączeniu:
    {attachments}
    
    {signature}
    """
    
    return template.format(
        court_name=context.get("court_name", ""),
        court_location=context.get("court_location", ""),
        case_number=context.get("case_number", ""),
        party_name=context.get("party_name", ""),
        party_role=context.get("party_role", ""),
        content=context.get("content", ""),
        attachments=context.get("attachments", ""),
        signature=context.get("signature", "")
    )


async def _generate_generic_document(service, doc_type: str, context: Dict[str, Any]) -> str:
    """Generate a generic legal document."""
    return f"""
    {doc_type.upper()}
    
    Data: {datetime.utcnow().strftime("%Y-%m-%d")}
    
    {context.get("content", "")}
    """


@celery_app.task(
    name="worker.tasks.document_tasks.validate_document",
    bind=True,
    max_retries=2
)
def validate_document(
    self,
    document_content: str,
    document_type: str,
    check_citations: bool = True
) -> Dict[str, Any]:
    """
    Validate a legal document for correctness and compliance.
    
    Args:
        document_content: The document text to validate
        document_type: Type of document
        check_citations: Whether to verify legal citations
        
    Returns:
        Validation results with any issues found
    """
    logger.info(f"Validating {document_type} document")
    
    async def _process():
        config_service = ConfigService()
        
        try:
            issues = []
            warnings = []
            
            # Check document structure
            if document_type == "pozew":
                required_sections = ["Powód:", "Pozwany:", "POZEW", "Wartość przedmiotu sporu:"]
                for section in required_sections:
                    if section not in document_content:
                        issues.append(f"Missing required section: {section}")
            
            # Check citations if requested
            if check_citations:
                # Look for article references
                import re
                citations = re.findall(r"art\.\s*\d+", document_content, re.IGNORECASE)
                
                if not citations and document_type in ["pozew", "odpowiedz_na_pozew"]:
                    warnings.append("No legal citations found in document")
            
            # Check for placeholder values
            placeholders = re.findall(r"\{[^}]+\}", document_content)
            if placeholders:
                issues.append(f"Unfilled placeholders found: {placeholders}")
            
            return {
                "status": "success" if not issues else "has_issues",
                "document_type": document_type,
                "issues": issues,
                "warnings": warnings,
                "is_valid": len(issues) == 0,
                "validated_at": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error validating document: {e}", exc_info=True)
            raise self.retry(exc=e)
    
    return run_async(_process())


@celery_app.task(
    name="worker.tasks.document_tasks.extract_document_metadata",
    bind=True
)
def extract_document_metadata(
    self,
    document_content: str,
    document_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract metadata from a legal document.
    
    Args:
        document_content: The document text
        document_type: Optional document type hint
        
    Returns:
        Extracted metadata
    """
    logger.info("Extracting document metadata")
    
    import re
    
    metadata = {
        "status": "success",
        "document_type": document_type,
        "extracted_at": datetime.utcnow().isoformat()
    }
    
    # Extract case number
    case_pattern = r"Sygnatura akt:\s*([^\n]+)"
    case_match = re.search(case_pattern, document_content)
    if case_match:
        metadata["case_number"] = case_match.group(1).strip()
    
    # Extract parties
    plaintiff_pattern = r"Powód:\s*([^\n]+)"
    plaintiff_match = re.search(plaintiff_pattern, document_content)
    if plaintiff_match:
        metadata["plaintiff"] = plaintiff_match.group(1).strip()
    
    defendant_pattern = r"Pozwany:\s*([^\n]+)"
    defendant_match = re.search(defendant_pattern, document_content)
    if defendant_match:
        metadata["defendant"] = defendant_match.group(1).strip()
    
    # Extract amount if present
    amount_pattern = r"Wartość przedmiotu sporu:\s*([\d\s,]+)\s*zł"
    amount_match = re.search(amount_pattern, document_content)
    if amount_match:
        amount_str = amount_match.group(1).replace(",", ".").replace(" ", "")
        try:
            metadata["claim_amount"] = float(amount_str)
        except:
            pass
    
    # Extract dates
    date_pattern = r"\d{1,2}[-./]\d{1,2}[-./]\d{2,4}"
    dates = re.findall(date_pattern, document_content)
    if dates:
        metadata["found_dates"] = dates
    
    # Extract legal citations
    citation_pattern = r"art\.\s*\d+[a-z]?(?:\s*§\s*\d+)?(?:\s*(?:KC|KPC|KK|KPK))"
    citations = re.findall(citation_pattern, document_content, re.IGNORECASE)
    if citations:
        metadata["legal_citations"] = list(set(citations))
    
    # Document statistics
    metadata["statistics"] = {
        "word_count": len(document_content.split()),
        "char_count": len(document_content),
        "line_count": len(document_content.split("\n"))
    }
    
    return metadata


@celery_app.task(
    name="worker.tasks.document_tasks.convert_document_format",
    bind=True
)
def convert_document_format(
    self,
    document_content: str,
    source_format: str,
    target_format: str
) -> Dict[str, Any]:
    """
    Convert document between formats (text, markdown, HTML, etc.).
    
    Args:
        document_content: The document content
        source_format: Source format (text, markdown, html)
        target_format: Target format (text, markdown, html, pdf)
        
    Returns:
        Converted document
    """
    logger.info(f"Converting document from {source_format} to {target_format}")
    
    try:
        converted_content = document_content
        
        if source_format == "text" and target_format == "markdown":
            # Convert plain text to markdown
            lines = document_content.split("\n")
            converted_lines = []
            
            for line in lines:
                if line.strip().isupper() and len(line.strip()) > 0:
                    # Headers
                    converted_lines.append(f"# {line.strip()}")
                elif line.strip().startswith("§"):
                    # Section headers
                    converted_lines.append(f"## {line.strip()}")
                elif line.strip().startswith("-") or line.strip().startswith("•"):
                    # Lists
                    converted_lines.append(line)
                else:
                    converted_lines.append(line)
            
            converted_content = "\n".join(converted_lines)
            
        elif source_format == "text" and target_format == "html":
            # Convert to basic HTML
            import html
            escaped = html.escape(document_content)
            converted_content = f"<html><body><pre>{escaped}</pre></body></html>"
            
        elif source_format == "markdown" and target_format == "html":
            # Simple markdown to HTML conversion
            converted_content = document_content
            converted_content = re.sub(r"^# (.+)$", r"<h1>\1</h1>", converted_content, flags=re.MULTILINE)
            converted_content = re.sub(r"^## (.+)$", r"<h2>\1</h2>", converted_content, flags=re.MULTILINE)
            converted_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", converted_content)
            converted_content = f"<html><body>{converted_content}</body></html>"
        
        return {
            "status": "success",
            "source_format": source_format,
            "target_format": target_format,
            "converted_content": converted_content,
            "converted_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error converting document: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }
