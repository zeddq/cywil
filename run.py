import uvicorn
import os
from app.core.config_service import get_config
from app.core.logger_manager import get_logger, correlation_context
from opentelemetry import trace
import asyncio
tracer = trace.get_tracer(__name__)


def run():
    with correlation_context() as correlation_id:
        with tracer.start_as_current_span("run", attributes={"correlation_id": correlation_id}):
            # Get a logger for this module
            logger = get_logger(__name__)
            logger.info("Starting application", extra={"extra_fields": {"log_level": LOG_LEVEL, "json_logs": JSON_LOGS}})
            
            # Load application config
            app_config = get_config()
            
            # Run Uvicorn programmatically
            uvicorn.run(
                "app.main:app",
                host=app_config.host,
                port=app_config.port,
                reload=app_config.reload,
                log_config=None  # We've already configured logging, so we pass None here
            ) 

if __name__ == "__main__":
    # Get log level and format from environment variables
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    JSON_LOGS = os.getenv("LOG_FORMAT", "json") == "json"

    run()
