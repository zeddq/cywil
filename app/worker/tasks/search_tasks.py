"""
Celery tasks for search operations (statutes and rulings).
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.logger_manager import get_logger
from app.worker.celery_app import celery_app
from app.worker.service_registry import get_worker_services

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
    name="worker.tasks.search_tasks.search_statutes",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def search_statutes(
    self, query: str, code_type: Optional[str] = None, limit: int = 10, use_semantic: bool = True
) -> Dict[str, Any]:
    """
    Search through statute documents (KC/KPC).

    Args:
        query: Search query
        code_type: Optional filter for specific code (KC or KPC)
        limit: Maximum number of results
        use_semantic: Whether to use semantic search

    Returns:
        Search results with relevant statute articles
    """
    logger.info(f"Searching statutes for query: {query}")

    async def _process():
        # Get shared services from worker registry
        services = get_worker_services()
        statute_service = services.statute_search

        try:

            # Perform search
            results = await statute_service.search_statute(
                query=query, top_k=limit, code=code_type
            )

            return {
                "status": "success",
                "query": query,
                "code_type": code_type,
                "result_count": len(results),
                "results": results,
                "searched_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error searching statutes: {e}", exc_info=True)
            raise self.retry(exc=e)

    return run_async(_process())


@celery_app.task(
    name="worker.tasks.search_tasks.search_rulings",
    bind=True,
    max_retries=3,
    default_retry_delay=30,
)
def search_rulings(
    self, query: str, filters: Optional[Dict[str, Any]] = None, limit: int = 10
) -> Dict[str, Any]:
    """
    Search through Supreme Court rulings.

    Args:
        query: Search query
        filters: Optional filters (date_range, court_type, etc.)
        limit: Maximum number of results

    Returns:
        Search results with relevant rulings
    """
    logger.info(f"Searching rulings for query: {query}")

    async def _process():
        # Get shared services from worker registry
        services = get_worker_services()
        db_manager = services.db_manager
        supreme_court_service = services.supreme_court

        try:

            # Apply filters if provided
            search_params = {"query": query, "limit": limit}

            if filters:
                if "date_from" in filters:
                    search_params["date_from"] = filters["date_from"]
                if "date_to" in filters:
                    search_params["date_to"] = filters["date_to"]
                if "court_type" in filters:
                    search_params["court_type"] = filters["court_type"]
                if "judge" in filters:
                    search_params["judge"] = filters["judge"]

            # Perform search
            results = await supreme_court_service.search_sn_rulings(**search_params)

            return {
                "status": "success",
                "query": query,
                "filters": filters,
                "result_count": len(results),
                "results": results,
                "searched_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error searching rulings: {e}", exc_info=True)
            raise self.retry(exc=e)
        finally:
            if supreme_court_service:
                await supreme_court_service.shutdown()
            if db_manager:
                await db_manager.shutdown()

    return run_async(_process())


@celery_app.task(name="worker.tasks.search_tasks.hybrid_search", bind=True, max_retries=3)
def hybrid_search(
    self, query: str, search_types: List[str] = ["statutes", "rulings"], limit_per_type: int = 5
) -> Dict[str, Any]:
    """
    Perform hybrid search across multiple document types.

    Args:
        query: Search query
        search_types: Types of documents to search
        limit_per_type: Maximum results per document type

    Returns:
        Combined search results from all sources
    """
    logger.info(f"Performing hybrid search for query: {query}")

    results = {
        "status": "success",
        "query": query,
        "search_types": search_types,
        "results": {},
        "total_count": 0,
        "searched_at": datetime.utcnow().isoformat(),
    }

    try:
        # Search statutes if requested
        if "statutes" in search_types:
            statute_results = search_statutes.apply_async(
                args=[query, None, limit_per_type, True]
            ).get(timeout=30)

            if statute_results["status"] == "success":
                results["results"]["statutes"] = statute_results["results"]
                results["total_count"] += statute_results["result_count"]

        # Search rulings if requested
        if "rulings" in search_types:
            ruling_results = search_rulings.apply_async(args=[query, None, limit_per_type]).get(
                timeout=30
            )

            if ruling_results["status"] == "success":
                results["results"]["rulings"] = ruling_results["results"]
                results["total_count"] += ruling_results["result_count"]

        return results

    except Exception as e:
        logger.error(f"Error in hybrid search: {e}", exc_info=True)
        return {"status": "error", "error": str(e), "query": query}


@celery_app.task(name="worker.tasks.search_tasks.find_similar_cases", bind=True)
def find_similar_cases(self, case_description: str, limit: int = 5) -> Dict[str, Any]:
    """
    Find similar cases based on case description.

    Args:
        case_description: Description of the case
        limit: Maximum number of similar cases to return

    Returns:
        Similar cases with relevance scores
    """
    logger.info("Finding similar cases")

    async def _process():
        # Get shared services from worker registry
        services = get_worker_services()
        config_service = services.config_service
        db_manager = services.db_manager

        try:
            # Search for similar rulings
            supreme_court_service = services.supreme_court

            # Use semantic search to find similar cases
            similar_rulings = await supreme_court_service.search_sn_rulings(
                query=case_description, top_k=limit
            )

            # Extract key patterns and precedents
            patterns = []
            for ruling in similar_rulings:
                patterns.append(
                    {
                        "case_id": ruling.docket,  # Use docket as case_id
                        "signature": ruling.docket,
                        "summary": ruling.paragraphs.text if ruling.paragraphs else "",
                        "relevance_score": ruling.score,
                        "date": ruling.date,
                        "court": "Sąd Najwyższy",  # Supreme Court
                    }
                )

            return {
                "status": "success",
                "case_description": (
                    case_description[:200] + "..."
                    if len(case_description) > 200
                    else case_description
                ),
                "similar_cases_count": len(patterns),
                "similar_cases": patterns,
                "analyzed_at": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            logger.error(f"Error finding similar cases: {e}", exc_info=True)
            return {"status": "error", "error": str(e)}
        finally:
            if supreme_court_service:
                await supreme_court_service.shutdown()
            if db_manager:
                await db_manager.shutdown()

    return run_async(_process())


@celery_app.task(name="worker.tasks.search_tasks.extract_legal_references", bind=True)
def extract_legal_references(self, text: str, validate: bool = True) -> Dict[str, Any]:
    """
    Extract and validate legal references from text.

    Args:
        text: Text to analyze for legal references
        validate: Whether to validate the references

    Returns:
        Extracted legal references with validation results
    """
    logger.info("Extracting legal references from text")

    import re

    references = {"statutes": [], "rulings": [], "regulations": []}

    # Extract statute references (art. X KC/KPC)
    statute_pattern = r"art\.\s*(\d+[a-z]?)(?:\s*§\s*(\d+))?(?:\s*(KC|KPC|KK|KPK|KPA))"
    statute_matches = re.findall(statute_pattern, text, re.IGNORECASE)

    for match in statute_matches:
        ref = {
            "article": match[0],
            "paragraph": match[1] if match[1] else None,
            "code": match[2].upper(),
            "full_reference": f"art. {match[0]}{' § ' + match[1] if match[1] else ''} {match[2].upper()}",
        }
        references["statutes"].append(ref)

    # Extract ruling references (signature patterns)
    ruling_patterns = [
        r"(?:sygn\.|sygnatura)\s*akt\s*([IVX]+\s+[A-Z]+\s+\d+/\d+)",
        r"(?:wyrok|postanowienie|uchwała)\s+SN\s+z\s+dnia\s+\d+\.\d+\.\d+\s+r\.,\s+([IVX]+\s+[A-Z]+\s+\d+/\d+)",
    ]

    for pattern in ruling_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            references["rulings"].append({"signature": match, "type": "supreme_court"})

    # Extract regulation references
    regulation_pattern = r"(?:Dz\.U\.|Dziennik Ustaw)\s+(?:z\s+)?(\d{4})\s+(?:r\.\s+)?(?:Nr\s+)?(\d+)\s+poz\.\s+(\d+)"
    regulation_matches = re.findall(regulation_pattern, text, re.IGNORECASE)

    for match in regulation_matches:
        references["regulations"].append(
            {
                "year": match[0],
                "number": match[1],
                "position": match[2],
                "full_reference": f"Dz.U. {match[0]} Nr {match[1]} poz. {match[2]}",
            }
        )

    # Validate references if requested
    validation_results = {}
    if validate and references["statutes"]:
        # Validate statute references
        for ref in references["statutes"]:
            # Check if article number is reasonable
            match = re.match(r"(\d+)", ref["article"]); article_num = int(match.group(1)) if match else 0
            if ref["code"] == "KC" and article_num > 1145:
                ref["validation"] = "warning: KC has 1145 articles"
            elif ref["code"] == "KPC" and article_num > 1217:
                ref["validation"] = "warning: KPC has 1217 articles"
            else:
                ref["validation"] = "valid"

    return {
        "status": "success",
        "text_length": len(text),
        "references": references,
        "total_references": sum(len(refs) for refs in references.values()),
        "extracted_at": datetime.utcnow().isoformat(),
    }


@celery_app.task(name="worker.tasks.search_tasks.build_search_index", bind=True)
def build_search_index(self, document_type: str, force_rebuild: bool = False) -> Dict[str, Any]:
    """
    Build or rebuild search index for a document type.

    Args:
        document_type: Type of documents to index (statutes, rulings)
        force_rebuild: Whether to force rebuild existing index

    Returns:
        Index building status and statistics
    """
    logger.info(f"Building search index for {document_type}")

    async def _process():
        # Get shared services from worker registry
        services = get_worker_services()
        config_service = services.config_service

        try:
            if document_type == "statutes":
                # Build statute index
                from app.worker.tasks.embedding_tasks import generate_statute_embeddings

                result = generate_statute_embeddings.apply_async(args=["all", force_rebuild]).get(
                    timeout=300
                )

                return {
                    "status": "success",
                    "document_type": document_type,
                    "index_stats": result,
                    "built_at": datetime.utcnow().isoformat(),
                }

            elif document_type == "rulings":
                # Build ruling index
                from app.worker.tasks.embedding_tasks import generate_ruling_embeddings

                result = generate_ruling_embeddings.apply_async(args=[None, force_rebuild]).get(
                    timeout=300
                )

                return {
                    "status": "success",
                    "document_type": document_type,
                    "index_stats": result,
                    "built_at": datetime.utcnow().isoformat(),
                }
            else:
                return {"status": "error", "error": f"Unknown document type: {document_type}"}

        except Exception as e:
            logger.error(f"Error building search index: {e}", exc_info=True)
            return {"status": "error", "error": str(e), "document_type": document_type}

    return run_async(_process())
