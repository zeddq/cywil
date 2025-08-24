import pytest
from app.worker.celery_app import celery_app

@pytest.fixture(scope="session")
def celery_config():
    return {
        'broker_url': 'memory://',
        'result_backend': 'cache+memory://',
        'task_always_eager': True,
        'task_eager_propagates': True,
    }

@pytest.fixture(scope="function")
def celery_app_eager(celery_config):
    celery_app.conf.update(celery_config)
    yield celery_app
    # Reset after test
    celery_app.conf.task_always_eager = False