"""
Example tests for the refactored services.
Demonstrates testing patterns and best practices.
"""
import pytest
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime

from app.core import (
    service_container,
    ServiceContainer,
    get_config,
    DatabaseManager,
    LLMManager,
    ToolExecutionError,
    ValidationError
)
from app.services import (
    StatuteSearchService,
    DocumentGenerationService,
    CaseManagementService,
    SupremeCourtService
)


# Fixtures
@pytest.fixture
def mock_config():
    """Mock configuration for testing"""
    config = Mock()
    config.openai.api_key.get_secret_value.return_value = "test-key"
    config.qdrant.host = "localhost"
    config.qdrant.port = 6333
    config.qdrant.collection_statutes = "test_statutes"
    config.qdrant.collection_rulings = "test_rulings"
    config.postgres.async_url = "postgresql+asyncpg://test:test@localhost/test"
    return config


@pytest.fixture
async def mock_db_manager():
    """Mock database manager"""
    db_manager = Mock(spec=DatabaseManager)
    db_manager._initialized = True
    
    # Mock session context manager
    session_mock = AsyncMock()
    session_mock.__aenter__.return_value = session_mock
    session_mock.__aexit__.return_value = None
    
    db_manager.get_session.return_value = session_mock
    return db_manager


@pytest.fixture
async def test_container(mock_db_manager):
    """Test service container with mocked dependencies"""
    container = ServiceContainer()
    container.register_singleton(DatabaseManager, mock_db_manager)
    return container


# StatuteSearchService Tests
class TestStatuteSearchService:
    """Tests for statute search service"""
    
    @pytest.fixture
    async def service(self, mock_config):
        """Create service instance with mocked dependencies"""
        with patch('app.services.statute_search_service.get_config', return_value=mock_config):
            mock_config_service = Mock()
            mock_llm_manager = Mock()
            service = StatuteSearchService(mock_config_service, mock_llm_manager)
            
            # Mock Qdrant client
            service._qdrant_client = AsyncMock()
            service._embedder = Mock()  # type: ignore
            service._llm = AsyncMock()  # type: ignore
            service._initialized = True
            
            return service
    
    async def test_search_statute_exact_article(self, service):
        """Test searching for exact article"""
        # Mock exact match response
        mock_result = Mock()
        mock_result.payload = {
            "article": "415",
            "text": "Kto z winy swej wyrządził drugiemu szkodę...",
            "code": "KC"
        }
        service._qdrant_client.scroll.return_value = ([mock_result], None)
        
        # Execute search
        results = await service.search_statute("art. 415 KC", top_k=1)
        
        # Assertions
        assert len(results) == 1
        assert results[0]["article"] == "415"
        assert results[0]["citation"] == "art. 415 KC"
        assert results[0]["score"] == 1.0
    
    async def test_search_statute_semantic(self, service):
        """Test semantic search"""
        # Mock embedding
        service._embedder.encode.return_value.tolist.return_value = [0.1] * 768
        
        # Mock search results
        mock_results = []
        for i in range(3):
            result = Mock()
            result.payload = {
                "article": f"41{i}",
                "text": f"Test article {i}",
                "code": "KC"
            }
            result.score = 0.9 - (i * 0.1)
            mock_results.append(result)
        
        service._qdrant_client.search.return_value = mock_results
        
        # Execute search
        results = await service.search_statute("odpowiedzialność deliktowa", top_k=3)
        
        # Assertions
        assert len(results) == 3
        assert all(r["score"] < 1.0 for r in results)
        service._embedder.encode.assert_called_once()
    
    async def test_summarize_passages(self, service):
        """Test passage summarization"""
        # Mock LLM response
        service._llm.ainvoke.return_value.content = "Podsumowanie przepisów..."
        
        passages = [
            {"citation": "art. 415 KC", "text": "Kto z winy swej..."},
            {"citation": "art. 416 KC", "text": "Osoba prawna..."}
        ]
        
        result = await service.summarize_passages(passages)
        
        assert result == "Podsumowanie przepisów..."
        service._llm.ainvoke.assert_called_once()


# DocumentGenerationService Tests
class TestDocumentGenerationService:
    """Tests for document generation service"""
    
    @pytest.fixture
    async def service(self, mock_config, mock_db_manager):
        """Create service with mocked dependencies"""
        with patch('app.services.document_generation_service.get_config', return_value=mock_config):
            # Mock other services
            statute_service = Mock(spec=StatuteSearchService)
            statute_service._initialized = True
            statute_service.search_statute = AsyncMock(return_value=[])
            
            sn_service = Mock(spec=SupremeCourtService)
            sn_service._initialized = True
            sn_service.search_sn_rulings = AsyncMock(return_value=[])
            sn_service.get_sn_ruling = AsyncMock(return_value=None)
            
            service = DocumentGenerationService(mock_db_manager, statute_service, sn_service)
            service._llm = AsyncMock()  # type: ignore
            service._initialized = True
            
            return service
    
    async def test_list_templates(self, service, mock_db_manager):
        """Test listing available templates"""
        # Mock database query
        mock_template = Mock()
        mock_template.id = "1"
        mock_template.name = "pozew_o_zaplate"
        mock_template.category = "pozwy"
        mock_template.summary = "Pozew o zapłatę"
        mock_template.variables = ["powod", "pozwany", "kwota"]
        mock_template.usage_count = 10
        mock_template.last_used = datetime.now()
        
        session = await mock_db_manager.get_session().__aenter__()
        session.execute.return_value.scalars.return_value.all.return_value = [mock_template]
        
        # Execute
        templates = await service.list_available_templates()
        
        # Assertions
        assert len(templates) == 1
        assert templates[0]["name"] == "pozew_o_zaplate"
        assert templates[0]["category"] == "pozwy"
    
    async def test_draft_document(self, service):
        """Test document generation"""
        # Mock template finding
        service.find_template = AsyncMock(return_value={
            "id": "1",
            "name": "pozew_o_zaplate",
            "content": "POZEW\n\nPowód: [[powod]]\nPozwany: [[pozwany]]\nKwota: [[kwota]]",
            "variables": ["powod", "pozwany", "kwota"]
        })
        
        # Mock template usage update
        service._update_template_usage = AsyncMock()
        
        # Mock LLM enhancement
        service._llm.ainvoke.return_value.content = "Enhanced document content..."
        
        # Execute
        result = await service.draft_document(
            doc_type="pozew_o_zaplate",
            facts={"powod": "Jan Kowalski", "pozwany": "ABC Sp. z o.o.", "kwota": "10000 zł"},
            goals=["Odzyskanie należności"]
        )
        
        # Assertions
        assert result["document_type"] == "pozew_o_zaplate"
        assert result["content"] == "Enhanced document content..."
        assert "metadata" in result
        service._update_template_usage.assert_called_once()


# CaseManagementService Tests
class TestCaseManagementService:
    """Tests for case management service"""
    
    @pytest.fixture
    async def service(self, mock_config, mock_db_manager):
        """Create service with mocked dependencies"""
        with patch('app.services.case_management_service.get_config', return_value=mock_config):
            service = CaseManagementService(mock_db_manager)
            service._initialized = True
            return service
    
    async def test_compute_deadline_business_days(self, service):
        """Test deadline computation with business days"""
        result = await service.compute_deadline("appeal", "2024-01-01")
        
        # Appeal is 14 business days
        assert result["event_type"] == "appeal"
        assert result["days_until_deadline"] == 14
        assert result["is_business_days"] is True
        
        # Check that weekend is skipped
        deadline = datetime.fromisoformat(result["deadline_date"])
        assert deadline.weekday() not in [5, 6]  # Not Saturday or Sunday
    
    async def test_compute_deadline_calendar_days(self, service):
        """Test deadline computation with calendar days"""
        result = await service.compute_deadline("payment", "2024-01-01")
        
        # Payment prescription is 3 years
        assert result["event_type"] == "payment"
        assert result["days_until_deadline"] == 3 * 365
        assert result["is_business_days"] is False
    
    async def test_update_case(self, service, mock_db_manager):
        """Test case update"""
        # Mock case retrieval
        mock_case = Mock()
        mock_case.id = "123"
        mock_case.reference_number = "ABC/2024"
        
        session = await mock_db_manager.get_session().__aenter__()
        session.execute.return_value.scalar_one_or_none.return_value = mock_case
        
        # Execute update
        result = await service.update_case(
            key="id",
            id="123",
            status="W toku",
            client_name="Jan Nowak"
        )
        
        # Assertions
        assert result["success"] is True
        assert "status" in result["updated_fields"]
        assert "client_name" in result["updated_fields"]
        assert mock_case.status == "W toku"
        assert mock_case.client_name == "Jan Nowak"


# Integration Tests
class TestServiceIntegration:
    """Integration tests for service interactions"""
    
    async def test_tool_registry_integration(self, mock_config):
        """Test that services register tools correctly"""
        from app.core import tool_registry
        
        # Check that tools are registered
        tools = tool_registry.list_tools()
        tool_names = [t.name for t in tools]
        
        expected_tools = [
            "search_statute",
            "summarize_passages",
            "list_available_templates",
            "draft_document",
            "validate_document",
            "describe_case",
            "update_case",
            "compute_deadline",
            "schedule_reminder",
            "search_sn_rulings",
            "summarize_sn_rulings"
        ]
        
        for expected in expected_tools:
            assert expected in tool_names, f"Tool '{expected}' not registered"
    
    async def test_service_health_checks(self, test_container):
        """Test service health check functionality"""
        # Create services with mocked dependencies
        mock_config_service = Mock()
        mock_llm_manager = Mock()
        services = [
            StatuteSearchService(mock_config_service, mock_llm_manager),
            CaseManagementService(test_container.get(DatabaseManager))
        ]
        
        for service in services:
            # Mock initialization
            service._initialized = True
            
            # Run health check
            result = await service.health_check()
            
            # Basic assertions
            assert result.status is not None
            assert result.timestamp is not None


# Error Handling Tests
class TestErrorHandling:
    """Test error handling scenarios"""
    
    async def test_tool_not_found(self):
        """Test handling of non-existent tool"""
        from app.services import execute_tool
        
        with pytest.raises(ValueError, match="Tool 'nonexistent' not found"):
            await execute_tool("nonexistent", {})
    
    async def test_validation_error(self):
        """Test tool argument validation"""
        from app.services import execute_tool
        
        # Missing required argument should raise validation error
        with pytest.raises(ValueError, match="Invalid arguments"):
            await execute_tool("search_statute", {})  # Missing 'query' parameter
    
    async def test_service_not_initialized(self, mock_config):
        """Test using uninitialized service"""
        with patch('app.services.statute_search_service.get_config', return_value=mock_config):
            mock_config_service = Mock()
            mock_llm_manager = Mock()
            service = StatuteSearchService(mock_config_service, mock_llm_manager)
            # Don't initialize
            
            with pytest.raises(RuntimeError, match="Service not initialized"):
                await service.search_statute("test query")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])