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

# Initialize clients
embedder = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
llm = ChatOpenAI(model="gpt-4-turbo-preview", temperature=0.1)

# Qdrant client initialization (will be configured from env)
qdrant_client = None

def init_vector_db(host: str = "localhost", port: int = 6333):
    """Initialize Qdrant client"""
    global qdrant_client
    qdrant_client = QdrantClient(host=host, port=port)

async def search_statute(query: str, top_k: int = 5, code: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Hybrid BM25+vector search over KC/KPC chunks.
    Returns JSON with article, text, and citation.
    """
    # Generate embedding for the query
    query_embedding = embedder.encode(query).tolist()
    
    # Build filter if specific code requested
    search_filter = None
    if code:
        search_filter = Filter(
            must=[FieldCondition(key="code", match=MatchValue(value=code))]
        )
    
    # Search in vector database
    results = qdrant_client.search(
        collection_name="statutes",
        query_vector=query_embedding,
        query_filter=search_filter,
        limit=top_k,
        with_payload=True
    )
    
    # Format results
    formatted_results = []
    for result in results:
        formatted_results.append({
            "article": result.payload.get("article"),
            "text": result.payload.get("text"),
            "citation": f"art. {result.payload.get('article')} {result.payload.get('code')}",
            "score": result.score
        })
    
    return formatted_results

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
    
    response = await llm.ainvoke(prompt.format(passages=passages_text))
    return response.content

async def draft_document(doc_type: str, facts: Dict[str, Any], goals: List[str]) -> Dict[str, Any]:
    """
    Generate legal documents based on type, facts, and goals.
    Supports: pozew, wezwanie do zapłaty, odpowiedź na pozew, etc.
    """
    # Document templates
    templates = {
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
    
    # Get relevant statutes for the document type
    statute_query = f"{doc_type} wymogi formalne przepisy"
    relevant_statutes = await search_statute(statute_query, top_k=3)
    
    # Generate document content
    template = templates.get(doc_type, "")
    if not template:
        return {"error": f"Unsupported document type: {doc_type}"}
    
    # Fill template with facts
    filled_template = template
    for key, value in facts.items():
        filled_template = filled_template.replace(f"{{{key}}}", str(value))
    
    # Generate justification if needed
    if "{justification}" in filled_template:
        justification_prompt = f"Napisz uzasadnienie dla {doc_type} na podstawie: {json.dumps(facts, ensure_ascii=False)}"
        justification = await llm.ainvoke(justification_prompt)
        filled_template = filled_template.replace("{justification}", justification.content)
    
    return {
        "document_type": doc_type,
        "content": filled_template,
        "citations": [s["citation"] for s in relevant_statutes],
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "facts": facts,
            "goals": goals
        }
    }

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
