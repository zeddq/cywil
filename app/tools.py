from typing import List, Dict, Any, Optional
import json
from datetime import datetime, timedelta
from pathlib import Path
import asyncio
from qdrant_client import QdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
import numpy as np
from sentence_transformers import SentenceTransformer
from sqlalchemy import select
from langchain_openai import ChatOpenAI
from langchain.prompts import PromptTemplate
import re
import logging

# Initialize logging
logger = logging.getLogger(__name__)

# Initialize clients
logger.info("Loading SentenceTransformer model from Hugging Face")
embedder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
logger.info("Initializing ChatOpenAI client")
llm = ChatOpenAI(model="gpt-4-turbo-preview", temperature=0.1)

# Qdrant client initialization (will be configured from env)
qdrant_client = None

def init_vector_db(host: str = "localhost", port: int = 6333):
    """Initialize Qdrant client"""
    global qdrant_client
    logger.info(f"Connecting to Qdrant vector database at {host}:{port}")
    qdrant_client = QdrantClient(host=host, port=port)

async def search_statute(query: str, top_k: int = 5, code: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Hybrid BM25+vector search over KC/KPC chunks.
    Returns JSON with article, text, and citation.
    """
    # Auto-initialize Qdrant client if not already done
    global qdrant_client
    if qdrant_client is None:
        from .config import settings
        logger.warning(f"Qdrant client not initialized, auto-initializing now (host: {settings.qdrant_host}, port: {settings.qdrant_port})")
        init_vector_db(settings.qdrant_host, settings.qdrant_port)
    
    # Check if query is looking for a specific article
    article_pattern = r'art\.?\s*(\d+[\w§]*)\s*(KC|KPC|k\.c\.|k\.p\.c\.)?'
    article_match = re.search(article_pattern, query, re.IGNORECASE)
    
    if article_match:
        article_num = article_match.group(1)
        requested_code = article_match.group(2)
        
        # Normalize code if provided
        if requested_code:
            requested_code = requested_code.upper().replace('K.C.', 'KC').replace('K.P.C.', 'KPC')
            code = requested_code
        
        # First try exact match
        logger.info(f"Attempting exact match for article {article_num} {code or ''}")
        
        # Build filter for exact article match
        must_conditions = [FieldCondition(key="article", match=MatchValue(value=article_num))]
        if code:
            must_conditions.append(FieldCondition(key="code", match=MatchValue(value=code)))
        
        exact_filter = Filter(must=must_conditions)
        
        # Try to find exact match
        exact_results = qdrant_client.scroll(
            collection_name="statutes",
            scroll_filter=exact_filter,
            limit=1,
            with_payload=True
        )
        
        if exact_results[0]:
            # Found exact match, return it first
            exact_match = exact_results[0][0]
            formatted_exact = {
                "article": exact_match.payload.get("article"),
                "text": exact_match.payload.get("text"),
                "citation": f"art. {exact_match.payload.get('article')} {exact_match.payload.get('code')}",
                "score": 1.0  # Perfect match
            }
            
            # If only one result requested, return just the exact match
            if top_k == 1:
                return [formatted_exact]
            
            # Otherwise, also get similar articles using vector search
            remaining_k = top_k - 1
            logger.info(f"Found exact match, searching for {remaining_k} similar articles")
        else:
            logger.info("No exact match found, falling back to vector search")
            remaining_k = top_k
            formatted_exact = None
    else:
        remaining_k = top_k
        formatted_exact = None
    
    # Generate embedding for the query
    logger.info(f"Generating embedding for query: {query[:100]}...")
    query_embedding = embedder.encode(query).tolist()
    
    # Build filter if specific code requested
    search_filter = None
    if code:
        search_filter = Filter(
            must=[FieldCondition(key="code", match=MatchValue(value=code))]
        )
    
    # Search in vector database
    logger.info(f"Searching Qdrant vector database for {remaining_k} results")
    results = qdrant_client.search(
        collection_name="statutes",
        query_vector=query_embedding,
        query_filter=search_filter,
        limit=remaining_k,
        with_payload=True
    )
    
    # Format results
    formatted_results = []
    
    # Add exact match first if found
    if formatted_exact:
        formatted_results.append(formatted_exact)
    
    # Add vector search results
    for result in results:
        # Skip if this is the same as our exact match
        if formatted_exact and result.payload.get("article") == formatted_exact["article"] and result.payload.get("code") == formatted_exact["citation"].split()[-1]:
            continue
            
        formatted_results.append({
            "article": result.payload.get("article"),
            "text": result.payload.get("text"),
            "citation": f"art. {result.payload.get('article')} {result.payload.get('code')}",
            "score": result.score
        })
    
    return formatted_results[:top_k]

async def summarize_passages(passages: List[Dict[str, Any]]) -> str:
    """
    Few-shot legal abstractive summary → coherent answer paragraphs.
    """
    # Prepare passages text
    passages_text = "\n\n".join([
        f"{p['citation']}: {p['text']}" for p in passages
    ])
    
    prompt = PromptTemplate(
        template="""Jako ekspert prawa cywilnego, podsumuj następujące przepisy w sposób jasny i zwięzły:

{passages}

Podsumowanie powinno:
1. Wyjaśnić kluczowe zasady prawne
2. Zachować precyzję terminologiczną
3. Wskazać praktyczne zastosowanie
4. Cytować konkretne artykuły

Podsumowanie:""",
        input_variables=["passages"]
    )
    
    logger.info("Calling OpenAI API for passage summarization")
    response = await llm.ainvoke(prompt.format(passages=passages_text))
    return response.content

async def find_template(template_type: str) -> Optional[Dict[str, Any]]:
    """
    Find template by type from database
    """
    from .database import sync_engine
    from .models import Template
    from sqlalchemy.orm import sessionmaker
    
    Session = sessionmaker(bind=sync_engine)
    session = Session()
    
    try:
        template = session.query(Template).filter_by(template_type=template_type).first()
        if template:
            return {
                'id': template.id,
                'name': template.name,
                'type': template.template_type,
                'content': template.content,
                'variables': template.variables,
                'description': template.description
            }
        return None
    finally:
        session.close()

async def draft_document(doc_type: str, facts: Dict[str, Any], goals: List[str]) -> Dict[str, Any]:
    """
    Generate legal documents based on type, facts, and goals.
    First tries to use database templates, falls back to hardcoded ones.
    """
    # Try to find template in database first
    db_template = await find_template(doc_type)
    
    if db_template:
        logger.info(f"Using database template for {doc_type}")
        template_content = db_template['content']
        template_variables = db_template['variables']
        
        # Update usage tracking
        await _update_template_usage(db_template['id'])
    else:
        # Fall back to hardcoded templates
        logger.info(f"No database template found for {doc_type}, using hardcoded template")
        hardcoded_templates = {
            "pozew_upominawczy": """POZEW W POSTĘPOWANIU UPOMINAWCZYM

Sąd Rejonowy w {court_location}
Wydział {court_division} Cywilny

Powód: {plaintiff_name}
{plaintiff_address}
PESEL/NIP: {plaintiff_id}

Pozwany: {defendant_name}
{defendant_address}
PESEL/NIP: {defendant_id}

Wartość przedmiotu sporu: {amount} zł

POZEW O ZAPŁATĘ

Wnoszę o:
1. Wydanie nakazu zapłaty w postępowaniu upominawczym i zasądzenie od pozwanego na rzecz powoda kwoty {amount} zł wraz z ustawowymi odsetkami za opóźnienie od dnia {due_date} do dnia zapłaty;
2. Zasądzenie od pozwanego na rzecz powoda kosztów procesu według norm przepisanych.

UZASADNIENIE

{justification}

Dowody:
{evidence_list}

Załączniki:
{attachments}

{signature}
{date}""",
            
            "wezwanie_do_zaplaty": """WEZWANIE DO ZAPŁATY

{creditor_name}
{creditor_address}

{debtor_name}
{debtor_address}

{city}, dnia {date}

PRZEDSĄDOWE WEZWANIE DO ZAPŁATY

Działając w imieniu {creditor_name}, wzywam Pana/Panią do zapłaty kwoty {amount} zł (słownie: {amount_words}) w terminie 7 dni od dnia otrzymania niniejszego wezwania.

Powyższa kwota wynika z {debt_source}.

{details}

W przypadku bezskutecznego upływu wyznaczonego terminu, sprawa zostanie skierowana na drogę postępowania sądowego, co naraża Pana/Panią na dodatkowe koszty procesu, w tym koszty zastępstwa procesowego.

Wpłaty należy dokonać na rachunek bankowy:
{bank_account}

{signature}"""
        }
        
        template_content = hardcoded_templates.get(doc_type, "")
        template_variables = []
        
        if not template_content:
            return {"error": f"No template found for document type: {doc_type}"}
    
    # Get relevant statutes for the document type
    statute_query = f"{doc_type} wymogi formalne przepisy"
    relevant_statutes = await search_statute(statute_query, top_k=3)
    
    # Fill template with facts
    filled_template = template_content
    for key, value in facts.items():
        filled_template = filled_template.replace(f"{{{key}}}", str(value))
    
    # Generate justification if needed
    if "{justification}" in filled_template:
        justification_prompt = f"Napisz uzasadnienie dla {doc_type} na podstawie: {json.dumps(facts, ensure_ascii=False)}"
        logger.info("Calling OpenAI API to generate document justification")
        justification = await llm.ainvoke(justification_prompt)
        filled_template = filled_template.replace("{justification}", justification.content)
    
    return {
        "document_type": doc_type,
        "content": filled_template,
        "citations": [s["citation"] for s in relevant_statutes],
        "template_variables": template_variables,
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "facts": facts,
            "goals": goals,
            "template_source": "database" if db_template else "hardcoded"
        }
    }

async def _update_template_usage(template_id: str):
    """Update template usage statistics"""
    from .database import sync_engine
    from .models import Template
    from sqlalchemy.orm import sessionmaker
    
    Session = sessionmaker(bind=sync_engine)
    session = Session()
    
    try:
        template = session.query(Template).filter_by(id=template_id).first()
        if template:
            template.usage_count = (template.usage_count or 0) + 1
            template.last_used = datetime.now()
            session.commit()
    finally:
        session.close()

async def list_available_templates() -> List[Dict[str, Any]]:
    """List all available templates"""
    from .database import sync_engine
    from .models import Template
    from sqlalchemy.orm import sessionmaker
    
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

async def validate_against_statute(draft: str, citations: List[str]) -> Dict[str, Any]:
    """
    Validate draft document against cited statutes to detect misquotes or outdated norms.
    """
    validation_results = {
        "is_valid": True,
        "issues": [],
        "suggestions": []
    }
    
    # Extract article references from draft
    article_pattern = r'art\.\s*(\d+[\w§]*)\s*(KC|KPC|k\.c\.|k\.p\.c\.)'
    found_citations = re.findall(article_pattern, draft, re.IGNORECASE)
    
    # Verify each citation
    for article, code in found_citations:
        # Search for the actual article text
        search_results = await search_statute(f"art. {article} {code}", top_k=1, code=code)
        
        if not search_results:
            validation_results["is_valid"] = False
            validation_results["issues"].append(
                f"Nie znaleziono art. {article} {code} - możliwy błąd w cytowaniu"
            )
        else:
            # Check if the article content matches the context in draft
            article_text = search_results[0]["text"]
            validation_prompt = f"""Sprawdź czy poniższy fragment dokumentu prawidłowo powołuje się na przepis:

Fragment dokumentu: {draft[:500]}...

Cytowany przepis - {search_results[0]['citation']}: {article_text}

Czy cytat jest prawidłowy? Odpowiedz TAK lub NIE i podaj krótkie uzasadnienie."""
            
            logger.info("Calling OpenAI API to validate document citation")
            validation_response = await llm.ainvoke(validation_prompt)
            if "NIE" in validation_response.content:
                validation_results["is_valid"] = False
                validation_results["issues"].append(
                    f"Nieprawidłowe powołanie się na {search_results[0]['citation']}"
                )
    
    return validation_results

def compute_deadline(event_type: str, event_date: str) -> Dict[str, Any]:
    """
    Calculate legal deadlines based on KPC term rules.
    """
    deadlines = {
        "payment": {
            "prescription": 3 * 365,  # 3 years for general claims
            "description": "Termin przedawnienia roszczenia (art. 118 KC)"
        },
        "appeal": {
            "deadline": 14,  # 14 days
            "description": "Termin na wniesienie apelacji (art. 369 KPC)"
        },
        "complaint": {
            "deadline": 7,  # 7 days
            "description": "Termin na wniesienie zażalenia (art. 394 § 2 KPC)"
        },
        "response_to_claim": {
            "deadline": 14,  # 14 days in summary proceedings
            "description": "Termin na sprzeciw od nakazu zapłaty (art. 505³ KPC)"
        },
        "cassation": {
            "deadline": 60,  # 2 months
            "description": "Termin na wniesienie skargi kasacyjnej (art. 398⁵ KPC)"
        }
    }
    
    # Parse event date
    event_datetime = datetime.fromisoformat(event_date)
    
    # Get deadline info
    deadline_info = deadlines.get(event_type, {})
    if not deadline_info:
        return {"error": f"Unknown event type: {event_type}"}
    
    # Calculate deadline date
    deadline_days = deadline_info.get("deadline", 0)
    deadline_date = event_datetime + timedelta(days=deadline_days)
    
    # Handle business days for procedural deadlines
    if event_type not in ["payment"]:  # Procedural deadlines skip weekends
        while deadline_date.weekday() in [5, 6]:  # Saturday or Sunday
            deadline_date += timedelta(days=1)
    
    return {
        "event_type": event_type,
        "event_date": event_date,
        "deadline_date": deadline_date.isoformat(),
        "days_until_deadline": deadline_days,
        "description": deadline_info["description"],
        "is_business_days": event_type != "payment"
    }

async def schedule_reminder(case_id: str, reminder_date: str, note: str) -> Dict[str, Any]:
    """
    Schedule a reminder for a specific case using Agent SDK automations.
    """
    # This would integrate with OpenAI Agent SDK automations
    # For now, we'll simulate the scheduling
    reminder = {
        "reminder_id": f"rem_{case_id}_{datetime.now().timestamp()}",
        "case_id": case_id,
        "scheduled_for": reminder_date,
        "note": note,
        "created_at": datetime.now().isoformat(),
        "status": "scheduled"
    }
    
    # In production, this would create an automation:
    # automation = await agent.automations.create(
    #     trigger={"type": "scheduled", "at": reminder_date},
    #     action={"type": "notify", "content": note, "case_id": case_id}
    # )
    
    return reminder

# Legacy functions for backward compatibility
def search_documents(query: str) -> List[Dict]:
    """Search through processed legal documents"""
    # Redirect to new search_statute function
    return asyncio.run(search_statute(query))

def analyze_contract(text: str) -> Dict:
    """Analyze a contract for key terms and potential issues"""
    # This would be implemented with more sophisticated analysis
    key_terms = []
    issues = []
    
    # Check for essential contract elements
    if "strony" not in text.lower() and "strona" not in text.lower():
        issues.append("Brak wyraźnego określenia stron umowy")
    
    if "przedmiot" not in text.lower():
        issues.append("Brak określenia przedmiotu umowy")
    
    if "termin" not in text.lower():
        issues.append("Brak określenia terminów wykonania")
    
    # Extract key monetary values
    money_pattern = r'(\d+(?:\s*\d+)*(?:,\d+)?)\s*(?:zł|złotych|PLN)'
    amounts = re.findall(money_pattern, text)
    if amounts:
        key_terms.extend([f"Kwota: {amount}" for amount in amounts])
    
    return {
        "key_terms": key_terms,
        "potential_issues": issues,
        "recommendations": [
            "Sprawdź zgodność z art. 353¹ KC (swoboda umów)",
            "Zweryfikuj kompletność essentialia negotii"
        ] if issues else []
    }

def extract_case_citations(text: str) -> List[str]:
    """Extract case citations from legal text"""
    citations = []
    
    # Pattern for Polish case citations
    patterns = [
        r'sygn\.\s*akt\s*([IVX]+\s*[A-Z]+\s*\d+/\d+)',  # Court signatures
        r'wyrok\s+z\s+dnia\s+\d+\s+\w+\s+\d{4}\s*r\.',  # Judgment dates
        r'uchwała\s+SN\s+z\s+dnia\s+\d+\s+\w+\s+\d{4}\s*r\.'  # Supreme Court resolutions
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        citations.extend(matches)
    
    return list(set(citations))

def summarize_document(text: str) -> str:
    """Generate a summary of a legal document"""
    # For now, return a simple extraction
    # In production, this would use LLM for summarization
    sentences = text.split('.')[:3]
    return '. '.join(sentences) + '...'
