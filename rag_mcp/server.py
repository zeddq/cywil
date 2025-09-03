from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

import numpy as np
from mcp.server.fastmcp import FastMCP

from .index import SimpleIndex


INDEX_DIR = os.environ.get("WEB_RAG_INDEX_DIR", "data/web_rag")


class WebRAGServer:
    def __init__(self, index_dir: str) -> None:
        self.index_dir = index_dir
        self.idx = SimpleIndex(index_dir)
        if self.idx.exists():
            self.idx.load()
        else:
            # Create empty in-memory state
            self.idx._emb = np.zeros((0, 1), dtype=np.float32)  # type: ignore[attr-defined]
            self.idx._meta = []  # type: ignore[attr-defined]

    def has_index(self) -> bool:
        return self.idx.exists() and len(getattr(self.idx, "_meta", [])) > 0


server = FastMCP(
    "web-rag",
    version="0.1.0",
    description=(
        "Local web RAG over a prebuilt index. "
        "Use the CLI to ingest sites, then search via this server."
    ),
)

state = WebRAGServer(INDEX_DIR)


@server.list_resources()
def list_resources() -> List[Dict[str, Any]]:
    # Expose resource scheme and a virtual listing
    resources: List[Dict[str, Any]] = []
    if not state.has_index():
        return resources
    # Only expose a virtual manifest resource with brief info
    resources.append(
        {
            "uri": "web-rag://index/manifest",
            "name": "Web RAG Index Manifest",
            "mimeType": "application/json",
            "description": "Summary of indexed chunks and where they came from.",
        }
    )
    return resources


@server.read_resource()
def read_resource(uri: str) -> Dict[str, Any]:
    if uri == "web-rag://index/manifest":
        # Minimal stats
        total = len(state.idx._meta)
        urls = sorted({m.url for m in state.idx._meta})
        body = {
            "chunks": total,
            "unique_urls": len(urls),
            "urls": urls[:100],  # truncate
        }
        return {
            "contents": [
                {
                    "uri": uri,
                    "mimeType": "application/json",
                    "text": json.dumps(body, ensure_ascii=False, indent=2),
                }
            ]
        }
    if uri.startswith("web-rag://chunk/"):
        cid = uri.split("/", 3)[-1]
        for m in state.idx._meta:
            if m.id == cid:
                return {
                    "contents": [
                        {
                            "uri": uri,
                            "mimeType": "text/plain",
                            "text": f"Title: {m.title}\nURL: {m.url}\nOffset: {m.offset}\n\n{m.text}",
                        }
                    ]
                }
        raise ValueError(f"Chunk not found: {cid}
")
    raise ValueError(f"Unknown resource: {uri}")


@server.tool()
def search(query: str, k: int = 5) -> Dict[str, Any]:
    """Semantic search over the local web RAG index.

    Returns a list of chunks with scores and resource URIs to fetch content.
    """
    if not state.has_index():
        return {"results": []}

    # Lazy-load model.json for dim; create a simple random projection fallback if missing
    model_info_path = os.path.join(state.index_dir, "model.json")
    if not os.path.exists(model_info_path):
        raise RuntimeError("Index missing model.json; re-run ingestion.")
    with open(model_info_path, "r", encoding="utf-8") as f:
        model_info = json.load(f)

    # For queries, we cannot embed without a model provider here. Instead, approximate by
    # using centroid of top-TF tokens is not viable. The recommended flow is to embed query
    # client-side. But most MCP clients expect server-side search. To keep things simple,
    # we support OpenAI embeddings if OPENAI_API_KEY is available; else error.
    provider = os.environ.get("WEB_RAG_QUERY_PROVIDER", model_info.get("provider", "openai"))
    model = os.environ.get("WEB_RAG_QUERY_MODEL", model_info.get("name", "text-embedding-3-small"))

    qvec = _embed_query(query, provider, model)
    pairs = state.idx.search(qvec, k=k)
    items = []
    for meta, score in pairs:
        items.append(
            {
                "id": meta.id,
                "score": float(score),
                "title": meta.title,
                "url": meta.url,
                "offset": meta.offset,
                "resource": f"web-rag://chunk/{meta.id}",
                "preview": meta.text[:320],
            }
        )
    return {"results": items}


def _embed_query(text: str, provider: str, model: str) -> np.ndarray:
    if provider == "openai":
        try:
            from openai import OpenAI  # type: ignore
        except Exception:
            raise RuntimeError("openai package not available for query embeddings")
        client = OpenAI()
        res = client.embeddings.create(model=model, input=[text])
        vec = np.array(res.data[0].embedding, dtype=np.float32)
        return vec
    elif provider == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception:
            raise RuntimeError("Please install sentence-transformers for local query embeddings")
        m = SentenceTransformer(model)
        vec = m.encode([text], show_progress_bar=False)[0]
        return np.array(vec, dtype=np.float32)
    else:
        raise RuntimeError(f"Unsupported provider: {provider}")


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()

