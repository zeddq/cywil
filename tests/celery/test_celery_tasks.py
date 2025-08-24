import pytest
from app.worker.tasks.statute_tasks import get_statute_ingestion_status
from app.worker.tasks.ruling_tasks import get_ruling_processing_status
from app.worker.tasks.embedding_tasks import get_embedding_statistics


@pytest.mark.celery
@pytest.mark.timeout(10)
def test_get_statute_ingestion_status(celery_app_eager):
    """Tasks should return a status dictionary for statute ingestion."""
    result = get_statute_ingestion_status.delay().get(timeout=10)
    assert isinstance(result, dict)
    assert "status" in result


@pytest.mark.celery
@pytest.mark.timeout(10)
def test_get_ruling_processing_status(celery_app_eager):
    """Tasks should return a status dictionary for ruling processing."""
    result = get_ruling_processing_status.delay().get(timeout=10)
    assert isinstance(result, dict)
    assert "status" in result


@pytest.mark.celery
@pytest.mark.timeout(10)
def test_get_embedding_statistics(celery_app_eager):
    """Tasks should return a status dictionary for embedding statistics."""
    result = get_embedding_statistics.delay().get(timeout=10)
    assert isinstance(result, dict)
    assert "status" in result

