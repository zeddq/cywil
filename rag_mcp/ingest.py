from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set, Tuple

import httpx
import numpy as np
import yaml
from tqdm import tqdm

from .index import SimpleIndex
from .utils import ensure_dir

try:
    import trafilatura  # type: ignore
except Exception as e:  # pragma: no cover - optional import
    trafilatura = None

try:
    from openai import OpenAI  # type: ignore
except Exception:
    OpenAI = None  # type: ignore


@dataclass
class IngestConfig:
    base_urls: List[str]
    allow_patterns: List[str]
    deny_patterns: List[str]
    max_pages: int = 500
    concurrency: int = 8
    chunk_chars: int = 1000
    chunk_overlap: int = 200
    out_dir: str = "data/web_rag"
    embedding_provider: str = "openai"  # or "sentence-transformers"
    embedding_model: str = "text-embedding-3-small"


def load_config(path: str) -> IngestConfig:
    with open(path, "r", encoding="utf-8") as f:
        y = yaml.safe_load(f)
    return IngestConfig(
        base_urls=y.get("base_urls", []),
        allow_patterns=y.get("allow_patterns", [".*"]),
        deny_patterns=y.get("deny_patterns", []),
        max_pages=y.get("max_pages", 500),
        concurrency=y.get("concurrency", 8),
        chunk_chars=y.get("chunk_chars", 1000),
        chunk_overlap=y.get("chunk_overlap", 200),
        out_dir=y.get("out_dir", "data/web_rag"),
        embedding_provider=y.get("embedding_provider", "openai"),
        embedding_model=y.get("embedding_model", "text-embedding-3-small"),
    )


def _allowed(url: str, allow: List[str], deny: List[str]) -> bool:
    if any(re.search(p, url) for p in deny):
        return False
    return any(re.search(p, url) for p in allow)


async def crawl(config: IngestConfig) -> List[Tuple[str, str, str]]:
    """Fetch pages and return list of (url, title, text)."""
    if trafilatura is None:
        raise RuntimeError("trafilatura is required for crawling; please install it")

    visited: Set[str] = set()
    to_visit: List[str] = list(dict.fromkeys(config.base_urls))
    results: List[Tuple[str, str, str]] = []

    async def fetch(client: httpx.AsyncClient, url: str) -> Optional[Tuple[str, str, str, List[str]]]:
        try:
            r = await client.get(url, timeout=20.0)
            r.raise_for_status()
        except Exception:
            return None
        html = r.text
        extracted = trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favour_recall=True)
        if not extracted:
            return None
        # Trafilatura returns plain text; title is not always included. Try to parse title from <title>
        title = None
        try:
            m = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
            if m:
                title = re.sub(r"\s+", " ", m.group(1)).strip()
        except Exception:
            title = None
        text = extracted.strip()
        # extract links (simple)
        links = re.findall(r"href=\"(.*?)\"", html)
        abs_links: List[str] = []
        from urllib.parse import urljoin
        for l in links:
            if l.startswith("javascript:") or l.startswith("#"):
                continue
            abs_links.append(urljoin(url, l))
        return url, (title or url), text, abs_links

    async with httpx.AsyncClient(follow_redirects=True, headers={"User-Agent": "web-rag-mcp/0.1"}) as client:
        pbar = tqdm(total=config.max_pages, desc="Crawling", unit="page")
        while to_visit and len(results) < config.max_pages:
            batch = []
            while to_visit and len(batch) < config.concurrency:
                u = to_visit.pop(0)
                if u in visited:
                    continue
                if not _allowed(u, config.allow_patterns, config.deny_patterns):
                    continue
                visited.add(u)
                batch.append(u)
            if not batch:
                break
            tasks = [fetch(client, u) for u in batch]
            fetched = await asyncio.gather(*tasks)
            for item in fetched:
                if not item:
                    continue
                url, title, text, links = item
                results.append((url, title, text))
                pbar.update(1)
                # queue more links within allowlist
                for l in links:
                    if l not in visited and _allowed(l, config.allow_patterns, config.deny_patterns):
                        to_visit.append(l)
        pbar.close()
    return results


def _chunk(text: str, size: int, overlap: int) -> List[Tuple[int, str]]:
    chunks = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + size)
        chunks.append((i, text[i:j]))
        if j == n:
            break
        i = j - overlap
        if i < 0:
            i = 0
    return chunks


def _embed_batch(texts: List[str], provider: str, model: str) -> np.ndarray:
    if provider == "openai":
        if OpenAI is None:
            raise RuntimeError("openai package not available")
        client = OpenAI()
        res = client.embeddings.create(model=model, input=texts)
        vecs = [d.embedding for d in res.data]
        return np.array(vecs, dtype=np.float32)
    elif provider == "sentence-transformers":
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception:
            raise RuntimeError("Please install sentence-transformers to use local embeddings")
        m = SentenceTransformer(model)
        vecs = m.encode(texts, show_progress_bar=False, normalize_embeddings=False)
        return np.array(vecs, dtype=np.float32)
    else:
        raise ValueError(f"Unknown embedding provider: {provider}")


def build_index(pages: List[Tuple[str, str, str]], cfg: IngestConfig) -> None:
    ensure_dir(cfg.out_dir)
    # Prepare chunks
    metas: List[Dict[str, str | int]] = []
    texts: List[str] = []
    for url, title, text in pages:
        for offset, chunk in _chunk(text, cfg.chunk_chars, cfg.chunk_overlap):
            cid = f"{abs(hash(url))}_{offset}"
            metas.append({
                "id": cid,
                "url": url,
                "title": title,
                "text": chunk,
                "offset": offset,
            })
            texts.append(chunk)

    # Embed in batches to avoid long requests
    all_vecs: List[np.ndarray] = []
    batch_size = 64 if cfg.embedding_provider == "openai" else 128
    for i in tqdm(range(0, len(texts), batch_size), desc="Embedding", unit="batch"):
        batch = texts[i:i + batch_size]
        vecs = _embed_batch(batch, cfg.embedding_provider, cfg.embedding_model)
        all_vecs.append(vecs)
    if not all_vecs:
        raise RuntimeError("No text chunks to embed.")
    mat = np.vstack(all_vecs)

    idx = SimpleIndex(cfg.out_dir)
    idx.save(
        mat,
        metas,
        model_info={
            "provider": cfg.embedding_provider,
            "name": cfg.embedding_model,
            "dim": int(mat.shape[1]),
        },
    )


def ingest_from_config(config_path: str) -> None:
    cfg = load_config(config_path)
    pages = asyncio.run(crawl(cfg))
    build_index(pages, cfg)

