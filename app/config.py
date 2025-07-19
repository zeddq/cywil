"""
Legacy configuration module - maintains backward compatibility.
New code should use app.core.config_service instead.
"""
import warnings
from .core.config_service import get_config, get_config_service

# Issue deprecation warning
warnings.warn(
    "app.config is deprecated. Use app.core.config_service instead.",
    DeprecationWarning,
    stacklevel=2
)

# Get the configuration instance
_config = get_config()

# Expose settings for backward compatibility
class Settings:
    """Legacy settings wrapper for backward compatibility"""
    
    def __init__(self):
        self._config = _config
    
    # API Configuration
    @property
    def app_name(self):
        return self._config.name
    
    @property
    def environment(self):
        return self._config.environment
    
    @property
    def debug(self):
        return self._config.debug
    
    # OpenAI Configuration
    @property
    def openai_api_key(self):
        return self._config.openai.api_key.get_secret_value()
    
    @property
    def openai_orchestrator_model(self):
        return self._config.openai.orchestrator_model
    
    @property
    def openai_summary_model(self):
        return self._config.openai.summary_model
    
    @property
    def openai_llm_model(self):
        return self._config.openai.llm_model
    
    # Vector Database Configuration
    @property
    def qdrant_host(self):
        return self._config.qdrant.host
    
    @property
    def qdrant_port(self):
        return self._config.qdrant.port
    
    @property
    def qdrant_collection(self):
        return self._config.qdrant.collection_statutes
    
    # PostgreSQL Configuration
    @property
    def postgres_host(self):
        return self._config.postgres.host
    
    @property
    def postgres_port(self):
        return self._config.postgres.port
    
    @property
    def postgres_db(self):
        return self._config.postgres.database
    
    @property
    def postgres_user(self):
        return self._config.postgres.user
    
    @property
    def postgres_password(self):
        return self._config.postgres.password.get_secret_value()
    
    # Redis Configuration
    @property
    def redis_host(self):
        return self._config.redis.host
    
    @property
    def redis_port(self):
        return self._config.redis.port
    
    # Security
    @property
    def secret_key(self):
        return self._config.security.secret_key.get_secret_value()
    
    @property
    def SECRET_KEY(self):
        return self.secret_key
    
    @property
    def algorithm(self):
        return self._config.security.algorithm
    
    @property
    def ALGORITHM(self):
        return self.algorithm
    
    @property
    def access_token_expire_minutes(self):
        return self._config.security.access_token_expire_minutes
    
    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self):
        return self.access_token_expire_minutes
    
    @property
    def registration_secret_keys(self):
        return ",".join(self._config.security.registration_keys)
    
    @property
    def registration_enabled(self):
        return self._config.security.registration_enabled
    
    # File Storage
    @property
    def upload_dir(self):
        return str(self._config.storage.get_path(self._config.storage.upload_dir))
    
    @property
    def embeddings_dir(self):
        return str(self._config.storage.get_path(self._config.storage.embeddings_dir))
    
    @property
    def chunks_dir(self):
        return str(self._config.storage.get_path(self._config.storage.chunks_dir))
    
    @property
    def pdfs_dir(self):
        return str(self._config.storage.get_path(self._config.storage.pdfs_dir))
    
    @property
    def jsonl_dir(self):
        return str(self._config.storage.get_path(self._config.storage.jsonl_dir))
    
    @property
    def database_url(self):
        """Construct PostgreSQL database URL"""
        return self._config.postgres.async_url
    
    @property
    def sync_database_url(self):
        """Construct synchronous PostgreSQL database URL"""
        return self._config.postgres.sync_url


# Create settings instance for backward compatibility
settings = Settings()