
from app.worker.celery_app import celery_app

if __name__ == "__main__":
    # The -A option specifies the application instance to use.
    # The worker command starts the worker process.
    # --loglevel=info sets the logging level.
    celery_app.worker_main(argv=['worker', '--loglevel=info']) 
