"""
Examples of using the centralized logger manager
"""
from app.worker.logging_config import LOGGING_CONFIG
from app.core.logger_manager import (
    get_logger, 
    configure_logging, 
    logger_manager,
    LOGGING_PRESETS,
    wrap_all_loggers
)
import asyncio
import logging.config

# Example 1: Simple usage in a module

def process_document(doc_id: str, logger: logging.Logger):
    logger.info("Processing document", extra={"doc_id": doc_id})
    try:
        # Some processing
        logger.debug("Document processed successfully")
        return {"status": "success"}
    except Exception as e:
        logger.error("Failed to process document", 
                    extra={"doc_id": doc_id, "error": str(e)},
                    exc_info=True)
        raise


# Example 2: Using in a class
class DocumentService:
    def __init__(self):

        self.logger = get_logger(f"{__name__}.{self.__class__.__name__}")
    
    async def analyze(self, doc_id: str):
        self.logger.info("Starting analysis", extra={"doc_id": doc_id})
        await asyncio.sleep(0.1)
        self.logger.info("Analysis complete", extra={"doc_id": doc_id})


# Example 3: Custom configuration
def setup_custom_logging():
    custom_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "custom": {
                "format": "[%(levelname)s] %(name)s - %(message)s (%(extra_fields)s)"
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "custom"
            },
            "app_file": {
                "class": "logging.handlers.RotatingFileHandler",
                "formatter": "custom",
                "filename": "app.log",
                "maxBytes": 10485760,  # 10MB
                "backupCount": 5
            }
        },
        "loggers": {
            "app": {
                "handlers": ["console", "app_file"],
                "level": "DEBUG"
            },
            "app.services": {
                "level": "INFO"
            }
        }
    }
    
    configure_logging(custom_config=custom_config)


# Example 4: Using presets
def setup_with_preset(environment: str):
    if environment == "dev":
        configure_logging(custom_config=LOGGING_PRESETS["development"])
    elif environment == "prod":
        configure_logging(custom_config=LOGGING_PRESETS["production"])
    else:
        configure_logging(custom_config=LOGGING_PRESETS["testing"])


# Example 5: Dynamic logger management
def manage_loggers_dynamically():
    # Get all logger info
    

    all_loggers = logger_manager.get_all_loggers_info()

    logger = get_logger(__name__)
    logger.info(f"Total loggers: {len(all_loggers)}")
    
    # Update specific logger level
    logger_manager.update_logger_level("app.services", "DEBUG")
    

    
    # Get info about a specific logger
    info = logger_manager.get_logger_info("app")
    logger.info(f"App logger info: {info}")
    
    # Add custom handler to a logger
    import logging
    custom_handler = logging.FileHandler("custom.log")
    custom_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    logger_manager.add_handler_to_logger("app.services", custom_handler)


# Example 6: Using with correlation context
async def process_with_context(logger: logging.Logger):
    from app.core.logger_manager import correlation_context
    

    
    with correlation_context() as correlation_id:

        logger = get_logger(__name__)
        logger.info("Starting process")  # Will automatically include correlation_id
        
        # Simulate work
        await asyncio.sleep(0.1)
        
        logger.info("Process complete")


if __name__ == "__main__":
    # Configure logging
    configure_logging(custom_config=LOGGING_CONFIG)
    
  

    logger = get_logger("app")
    
    # Use logger
    logger.info("Example started")
    
    # Process document
    process_document("doc123", logger)
    
    # Run async example
    asyncio.run(process_with_context(logger))
    
    # Show logger management
    manage_loggers_dynamically()
