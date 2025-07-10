import os
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    """Application settings with environment variable support"""
    
    # API Configuration
    app_name: str = "AI Paralegal POC"
    environment: str = "development"
    debug: bool = True
    
    # OpenAI Configuration
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_orchestrator_model: str = "gpt-4.1-2025-04-14"
    openai_summary_model: str = "gpt-4o"
    openai_llm_model: str = "o3-mini"
    
    # Vector Database Configuration
    qdrant_host: str = os.getenv("QDRANT_HOST", "localhost")
    qdrant_port: int = int(os.getenv("QDRANT_PORT", "6333"))
    qdrant_collection: str = "statutes"
    
    # PostgreSQL Configuration
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "paralegal")
    postgres_user: str = os.getenv("POSTGRES_USER", "paralegal")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "paralegal")
    
    # Redis Configuration
    redis_host: str = os.getenv("REDIS_HOST", "localhost")
    redis_port: int = int(os.getenv("REDIS_PORT", "6379"))
    
    # Security
    secret_key: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")  # For JWT compatibility
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Registration Secret Keys - comma separated list of valid keys
    registration_secret_keys: str = os.getenv("REGISTRATION_SECRET_KEYS", "default-registration-key-change-in-production")
    registration_enabled: bool = os.getenv("REGISTRATION_ENABLED", "True").lower() == "true"
    
    # File Storage
    upload_dir: str = "data/uploads"
    embeddings_dir: str = "data/embeddings"
    chunks_dir: str = "data/chunks"
    pdfs_dir: str = "data/pdfs"
    jsonl_dir: str = "data/jsonl"
    
    @property
    def database_url(self) -> str:
        """Construct PostgreSQL database URL"""
        return f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def sync_database_url(self) -> str:
        """Construct synchronous PostgreSQL database URL"""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    class Config:
        env_file = ".env"
        case_sensitive = False

# Create settings instance
settings = Settings()
