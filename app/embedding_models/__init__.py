"""
Models module for embedding interfaces and implementations.
"""

from .embedding_factory import EmbeddingFactory, embedding_factory
from .embedding_interface import (
    EmbeddingModel,
    HuggingFaceEmbedder,
    LocalEmbedder,
    OpenAIEmbedder,
)

__all__ = [
    "EmbeddingModel",
    "LocalEmbedder", 
    "OpenAIEmbedder",
    "HuggingFaceEmbedder",
    "EmbeddingFactory",
    "embedding_factory",
]
