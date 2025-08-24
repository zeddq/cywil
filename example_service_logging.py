"""
Example of how to use service_operation_logger decorator
"""
from app.core.logging_utils import service_operation_logger
import asyncio


class DocumentService:
    """Example service that processes documents"""
    
    @service_operation_logger("DocumentService")
    async def analyze_document(self, doc_id: str):
        """Async method with logging"""
        print(f"Analyzing document {doc_id}")
        await asyncio.sleep(0.1)  # Simulate work
        return {"doc_id": doc_id, "status": "analyzed"}
    
    @service_operation_logger("DocumentService")
    def validate_document(self, doc_id: str):
        """Sync method with logging"""
        print(f"Validating document {doc_id}")
        # Simulate work
        return {"doc_id": doc_id, "valid": True}
    
    @service_operation_logger("DocumentService")
    async def process_batch(self, doc_ids: list):
        """Method that might fail"""
        if not doc_ids:
            raise ValueError("No documents provided")
        
        results = []
        for doc_id in doc_ids:
            result = await self.analyze_document(doc_id)
            results.append(result)
        return results


class SearchService:
    """Another service example"""
    
    @service_operation_logger("SearchService")
    async def search_legal_texts(self, query: str, limit: int = 10):
        """Search operation with logging"""
        print(f"Searching for: {query}")
        await asyncio.sleep(0.2)  # Simulate search
        return {
            "query": query,
            "results": [f"Result {i}" for i in range(limit)],
            "total": limit
        }


# Example usage
async def main():
    doc_service = DocumentService()
    search_service = SearchService()
    
    # These will all be logged with service name, operation name, duration, and status
    
    # Async operation - success
    result = await doc_service.analyze_document("doc123")
    print(f"Analysis result: {result}")
    
    # Sync operation - success
    result = doc_service.validate_document("doc456")
    print(f"Validation result: {result}")
    
    # Another service - success
    search_results = await search_service.search_legal_texts("civil code article 415")
    print(f"Found {search_results['total']} results")
    
    # Operation that fails - will log error
    try:
        await doc_service.process_batch([])
    except ValueError as e:
        print(f"Expected error: {e}")
    
    # Batch operation - success
    batch_results = await doc_service.process_batch(["doc1", "doc2", "doc3"])
    print(f"Processed {len(batch_results)} documents")


if __name__ == "__main__":
    asyncio.run(main())