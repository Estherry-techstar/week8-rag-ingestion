from fastapi import FastAPI, HTTPException

from app.chunking import fixed_size_chunks, structure_aware_chunks
from app.extract import extract_pages
from app.store import index_chunks, search
from app.upload import router as upload_router

app = FastAPI(title="Week 8 – RAG Ingestion")
app.include_router(upload_router)


def _chunk_with(strategy: str, pages: list[dict]) -> list[dict]:
    """Run the requested chunking strategy, or fail with a clear message."""
    if strategy == "fixed_size":
        result = fixed_size_chunks(pages)
    elif strategy == "structure_aware":
        result = structure_aware_chunks(pages)
    else:
        raise HTTPException(
            400,
            f"Unknown strategy '{strategy}'. "
            "Use 'fixed_size' or 'structure_aware'.",
        )

    if not result:
        raise HTTPException(422, "No chunks met the minimum size threshold.")
    return result


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/documents/{doc_id}/preview")
def preview(doc_id: str):
    """Show extracted text per page, to verify extraction worked."""
    pages = extract_pages(doc_id)
    return {
        "doc_id": doc_id,
        "page_count": len(pages),
        "total_chars": sum(len(p["text"]) for p in pages),
        "pages": [
            {"page": p["page"], "preview": p["text"][:300]} for p in pages
        ],
    }


@app.get("/documents/{doc_id}/chunks")
def chunks(doc_id: str, strategy: str = "fixed_size"):
    """Preview chunks and their size distribution, without storing anything."""
    result = _chunk_with(strategy, extract_pages(doc_id))

    token_counts = [c["token_count"] for c in result]
    return {
        "doc_id": doc_id,
        "strategy": strategy,
        "chunk_count": len(result),
        "avg_tokens": round(sum(token_counts) / len(token_counts), 1),
        "min_tokens": min(token_counts),
        "max_tokens": max(token_counts),
        "chunks": [
            {
                "chunk_index": c["chunk_index"],
                "page": c["page"],
                "token_count": c["token_count"],
                "preview": c["text"][:200],
            }
            for c in result
        ],
    }


@app.post("/documents/{doc_id}/index")
def index(
    doc_id: str,
    strategy: str = "structure_aware",
    source: str | None = None,
):
    """Chunk, embed, and store a document in the vector store."""
    result = _chunk_with(strategy, extract_pages(doc_id))
    summary = index_chunks(result, doc_id=doc_id, source=source or doc_id)
    return {"doc_id": doc_id, "strategy": strategy, **summary}


@app.get("/search")
def search_endpoint(q: str, n: int = 5, strategy: str | None = None):
    """Retrieve chunks relevant to a query, with citations."""
    return {"query": q, "strategy": strategy, "results": search(q, n, strategy)}