"""
Enhanced configuration service with validation and hierarchical organization.
"""
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator, SecretStr
from pydantic_settings import SettingsConfigDict, BaseSettings
from pathlib import Path
import logging
from functools import lru_cache
from fastapi import Request
from .service_interface import ServiceInterface, HealthCheckResult, ServiceStatus

logger = logging.getLogger(__name__)


class OpenAIConfig(BaseSettings):
    """OpenAI-specific configuration"""
    api_key: SecretStr = Field(default="", env='OPENAI_API_KEY')
    orchestrator_model: str = Field(default="gpt-4.1", env='OPENAI_ORCHESTRATOR_MODEL')
    summary_model: str = Field(default="gpt-4o", env='OPENAI_SUMMARY_MODEL')
    llm_model: str = Field(default="o3-mini", env='OPENAI_LLM_MODEL')
    max_retries: int = Field(default=3, env='OPENAI_MAX_RETRIES')
    timeout: int = Field(default=120, env='OPENAI_TIMEOUT')
    
    model_config = SettingsConfigDict(env_prefix='OPENAI_')


class QdrantConfig(BaseSettings):
    """Qdrant vector database configuration"""
    host: str = Field(default="qdrant-service", env='QDRANT_HOST')
    port: int = Field(default=6333, env='QDRANT_PORT')
    api_key: Optional[SecretStr] = Field(default="qdrant-api-key", env='QDRANT_API_KEY')
    collection_statutes: str = Field(default="statutes", env='QDRANT_COLLECTION_STATUTES')
    collection_rulings: str = Field(default="sn_rulings", env='QDRANT_COLLECTION_RULINGS')
    timeout: int = Field(default=60, env='QDRANT_TIMEOUT')
    
    model_config = SettingsConfigDict(env_prefix='QDRANT_')
    
    @property
    def url(self) -> str:
        """Construct Qdrant URL"""
        return f"http://{self.host}:{self.port}"


class PostgresConfig(BaseSettings):
    """PostgreSQL database configuration"""
    host: str = Field(default="postgres-service", env='POSTGRES_HOST')
    port: int = Field(default=5432, env='POSTGRES_PORT')
    database: str = Field(default="paralegal", env='POSTGRES_DB')
    user: SecretStr = Field(default="postgres", env='POSTGRES_USER')
    password: SecretStr = Field(default="postgres", env='POSTGRES_PASSWORD')
    pool_size: int = Field(default=10, env='POSTGRES_POOL_SIZE')
    max_overflow: int = Field(default=20, env='POSTGRES_MAX_OVERFLOW')
    
    model_config = SettingsConfigDict(env_prefix='POSTGRES_')
    
    @property
    def async_url(self) -> str:
        """Construct async PostgreSQL URL"""
        return f"postgresql+asyncpg://{self.user.get_secret_value()}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"
    
    @property
    def sync_url(self) -> str:
        """Construct sync PostgreSQL URL"""
        return f"postgresql://{self.user.get_secret_value()}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.database}"


class RedisConfig(BaseSettings):
    """Redis configuration for caching and session management"""
    host: str = Field(default="redis-service", env='REDIS_HOST')
    port: int = Field(default=6379, env='REDIS_PORT')
    db: int = Field(default=0, env='REDIS_DB')
    password: Optional[SecretStr] = Field(default="redis", env='REDIS_PASSWORD')
    
    model_config = SettingsConfigDict(env_prefix='REDIS_')
    
    @property
    def url(self) -> str:
        """Construct Redis URL"""
        if self.password:
            return f"redis://:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.db}"
        return f"redis://{self.host}:{self.port}/{self.db}"


class SecurityConfig(BaseSettings):
    """Security-related configuration"""
    secret_key: SecretStr = Field(default="secret", env='SECRET_KEY')
    algorithm: str = Field(default="HS256", env='JWT_ALGORITHM')
    access_token_expire_minutes: int = Field(default=30, env='ACCESS_TOKEN_EXPIRE_MINUTES')
    refresh_token_expire_days: int = Field(default=7, env='REFRESH_TOKEN_EXPIRE_DAYS')
    registration_enabled: bool = Field(default=True, env='REGISTRATION_ENABLED')
    registration_keys: List[str] = Field(default_factory=list, env='REGISTRATION_SECRET_KEYS')
    
    model_config = SettingsConfigDict(env_prefix='')
    
    @field_validator('registration_keys', mode='before')
    def parse_registration_keys(cls, v):
        if isinstance(v, str):
            return [key.strip() for key in v.split(',') if key.strip()]
        return v


class StorageConfig(BaseSettings):
    """File storage configuration"""
    base_dir: Path = Field(default=Path("data"), env='STORAGE_BASE_DIR')
    upload_dir: str = Field(default="uploads", env='STORAGE_UPLOAD_DIR')
    embeddings_dir: str = Field(default="embeddings", env='STORAGE_EMBEDDINGS_DIR')
    chunks_dir: str = Field(default="chunks", env='STORAGE_CHUNKS_DIR')
    pdfs_dir: str = Field(default="pdfs", env='STORAGE_PDFS_DIR')
    jsonl_dir: str = Field(default="jsonl", env='STORAGE_JSONL_DIR')
    max_upload_size: int = Field(default=10 * 1024 * 1024, env='MAX_UPLOAD_SIZE')  # 10MB
    
    model_config = SettingsConfigDict(env_prefix='STORAGE_')
    
    def get_path(self, subdir: str) -> Path:
        """Get full path for a subdirectory"""
        path = self.base_dir / subdir
        path.mkdir(parents=True, exist_ok=True)
        return path


class AppConfig(BaseSettings):
    """Main application configuration"""
    name: str = Field(default="AI Paralegal POC", env='APP_NAME')
    environment: str = Field(default="development", env='ENVIRONMENT')
    debug: bool = Field(default=True, env='DEBUG')
    log_level: str = Field(default="DEBUG", env='LOG_LEVEL')
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], env='CORS_ORIGINS')
    host: str = Field(default="0.0.0.0", env='HOST')
    port: int = Field(default=8000, env='PORT')
    reload: bool = Field(default=True, env='RELOAD')

    # Sub-configurations
    openai: OpenAIConfig = Field(default_factory=OpenAIConfig)
    qdrant: QdrantConfig = Field(default_factory=QdrantConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)
    redis: RedisConfig = Field(default_factory=RedisConfig)
    security: SecurityConfig = Field(default_factory=SecurityConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore'
    )
    
    @field_validator('cors_origins', mode='before')
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(',') if origin.strip()]
        return v
    
    @field_validator('environment')
    def validate_environment(cls, v):
        allowed = ['development', 'staging', 'production']
        if v not in allowed:
            raise ValueError(f"Environment must be one of {allowed}")
        return v


class ConfigService(ServiceInterface):
    """
    Configuration service providing centralized access to all settings.
    Implements singleton pattern for consistent configuration across the app.
    """
    _config: Optional[AppConfig] = None
    
    def __init__(self):
        super().__init__("ConfigService")
        if self._config is None:
            self._config = self._load_config()
            self._validate_config()
            self._setup_logging()

    async def _initialize_impl(self) -> None:
        """Initialize configuration service"""
        pass
    
    async def _shutdown_impl(self) -> None:
        """Shutdown configuration service"""
        pass
    
    @staticmethod
    def _load_config() -> AppConfig:
        """Load configuration from environment"""
        try:
            config = AppConfig()
            logger.info(f"Configuration loaded for environment: {config.environment}")
            return config
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise
    
    def _validate_config(self):
        """Validate configuration values"""
        # Check required secrets in production
        if self._config.environment == 'production':
            if self._config.security.secret_key.get_secret_value() == 'dev-secret-key-change-in-production':
                raise ValueError("SECRET_KEY must be changed in production")
            
            if not self._config.openai.api_key.get_secret_value():
                raise ValueError("OPENAI_API_KEY is required")
    
    def _setup_logging(self):
        """Configure logging based on settings"""
        logging.basicConfig(
            level=logging.DEBUG,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    async def _health_check_impl(self) -> HealthCheckResult:
        return HealthCheckResult(
            status=ServiceStatus.HEALTHY,
            message="Configuration service is healthy"
        )
    
    @property
    def config(self) -> AppConfig:
        """Get the configuration object"""
        return self._config
    
    def get_database_url(self, async_mode: bool = True) -> str:
        """Get database URL based on mode"""
        return self._config.postgres.async_url if async_mode else self._config.postgres.sync_url
    
    def get_storage_path(self, subdir: str) -> Path:
        """Get storage path for a specific subdirectory"""
        return self._config.storage.get_path(subdir)
    
    def is_production(self) -> bool:
        """Check if running in production"""
        return self._config.environment == 'production'
    
    def is_development(self) -> bool:
        """Check if running in development"""
        return self._config.environment == 'development'
    
    def reload(self):
        """Reload configuration (useful for testing)"""
        self._config = self._load_config()
        self._validate_config()
        logger.info("Configuration reloaded")


# Convenience function for accessing config
def get_config() -> AppConfig:
    """Get current configuration"""
    return ConfigService().config
