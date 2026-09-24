import hashlib
from functools import lru_cache

import chromadb

from app.config import settings


@lru_cache(maxsize=1)
def _embedder():
    """Load the embedding model once and reuse it."""
    if settings.embedding_provider == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)

        def embed(texts: list[str]) -> list[list[float]]:
            resp = client.embeddings.create(
                model=settings.openai_embedding_model, input=texts
            )
            return [item.embedding for item in resp.data]

        return embed

    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(settings.local_embedding_model)

    def embed(texts: list[str]) -> list[list[float]]:
        return model.encode(texts, show_progress_bar=False).tolist()

    return embed


@lru_cache(maxsize=1)
def _collection():
    client = chromadb.PersistentClient(path=settings.chroma_dir)
    return client.get_or_create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def index_chunks(chunks: list[dict], doc_id: str, source: str) -> dict:
    """Embed chunks and store them with metadata. Returns a summary."""
    collection = _collection()
    embed = _embedder()

    texts = [c["text"] for c in chunks]
    embeddings = embed(texts)

    ids, metadatas = [], []
    for c in chunks:
        content_hash = hashlib.sha256(c["text"].encode()).hexdigest()[:16]
        ids.append(f"{doc_id}:{c['strategy']}:{c['chunk_index']}")
        metadatas.append(
            {
                "doc_id": doc_id,
                "source": source,
                "page": c["page"],
                "chunk_index": c["chunk_index"],
                "strategy": c["strategy"],
                "token_count": c["token_count"],
                "content_hash": content_hash,
            }
        )

    collection.upsert(
        ids=ids, documents=texts, embeddings=embeddings, metadatas=metadatas
    )

    return {
        "indexed": len(ids),
        "collection_total": collection.count(),
        "embedding_model": (
            settings.openai_embedding_model
            if settings.embedding_provider == "openai"
            else settings.local_embedding_model
        ),
        "vector_dimensions": len(embeddings[0]),
    }


def search(query: str, n_results: int = 5, strategy: str | None = None) -> list[dict]:
    """Retrieve the closest chunks, optionally filtered to one strategy."""
    collection = _collection()
    embed = _embedder()

    result = collection.query(
        query_embeddings=embed([query]),
        n_results=n_results,
        where={"strategy": strategy} if strategy else None,
    )

    hits = []
    for text, meta, distance in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append(
            {
                "text": text,
                "source": meta["source"],
                "page": meta["page"],
                "strategy": meta["strategy"],
                "similarity": round(1 - distance, 4),
                "citation": f"{meta['source']}, p.{meta['page']}",
            }
        )
    return hits