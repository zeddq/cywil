"""
Factory for creating embedding models based on configuration.
"""

from typing import Dict, Optional

from .embedding_interface import EmbeddingModel, HuggingFaceEmbedder, LocalEmbedder, OpenAIEmbedder


class EmbeddingFactory:
    """Factory for creating embedding model instances."""
    
    _instance: Optional['EmbeddingFactory'] = None
    _models: Dict[str, EmbeddingModel] = {}
    
    def __new__(cls) -> 'EmbeddingFactory':
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def create_local_embedder(
        self, 
        model_name: str = "paraphrase-multilingual-mpnet-base-v2",
        cache_key: Optional[str] = None
    ) -> EmbeddingModel:
        """Create or retrieve cached LocalEmbedder."""
        key = cache_key or f"local:{model_name}"
        
        if key not in self._models:
            self._models[key] = LocalEmbedder(model_name)
        
        return self._models[key]
    
    def create_openai_embedder(
        self,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        cache_key: Optional[str] = None
    ) -> EmbeddingModel:
        """Create or retrieve cached OpenAIEmbedder."""
        key = cache_key or f"openai:{model_name}"
        
        if key not in self._models:
            self._models[key] = OpenAIEmbedder(api_key, model_name)
        
        return self._models[key]
    
    def create_huggingface_embedder(
        self,
        model_name: str,
        cache_key: Optional[str] = None
    ) -> EmbeddingModel:
        """Create or retrieve cached HuggingFaceEmbedder."""
        key = cache_key or f"hf:{model_name}"
        
        if key not in self._models:
            self._models[key] = HuggingFaceEmbedder(model_name)
        
        return self._models[key]
    
    def get_model(self, key: str) -> Optional[EmbeddingModel]:
        """Get cached model by key."""
        return self._models.get(key)
    
    def list_models(self) -> Dict[str, str]:
        """List all cached models."""
        return {key: type(model).__name__ for key, model in self._models.items()}
    
    def clear_cache(self) -> None:
        """Clear all cached models."""
        self._models.clear()
    
    def remove_model(self, key: str) -> bool:
        """Remove specific model from cache."""
        if key in self._models:
            del self._models[key]
            return True
        return False


# Global factory instance
embedding_factory = EmbeddingFactory()