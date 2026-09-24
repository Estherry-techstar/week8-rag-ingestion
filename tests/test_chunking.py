from app.chunking import (
    MIN_CHUNK_TOKENS,
    count_tokens,
    fixed_size_chunks,
    structure_aware_chunks,
)

LONG_PAGE = [
    {
        "page": 1,
        "text": "\n\n".join(
            f"Paragraph {i}. " + "This sentence provides filler content. " * 12
            for i in range(6)
        ),
    }
]

FOOTER_PAGE = [{"page": 9, "text": "example.edu.ng 9"}]


def test_fixed_size_respects_target():
    chunks = fixed_size_chunks(LONG_PAGE, chunk_tokens=100, overlap_tokens=20)
    assert chunks
    assert all(c["token_count"] <= 100 for c in chunks)


def test_fixed_size_overlaps():
    """Consecutive chunks should share text, so boundary facts survive."""
    chunks = fixed_size_chunks(LONG_PAGE, chunk_tokens=100, overlap_tokens=30)
    assert len(chunks) > 1
    tail = chunks[0]["text"].split()[-5:]
    assert " ".join(tail) in chunks[1]["text"]


def test_structure_aware_respects_target():
    chunks = structure_aware_chunks(LONG_PAGE, chunk_tokens=100)
    assert chunks
    assert all(c["token_count"] <= 100 for c in chunks)


def test_structure_aware_keeps_sentences_whole():
    """No chunk should begin mid-sentence."""
    chunks = structure_aware_chunks(LONG_PAGE, chunk_tokens=150)
    for c in chunks:
        assert c["text"][0].isupper() or c["text"][0].isdigit()


def test_page_numbers_preserved():
    pages = [{"page": 4, "text": "Content on page four. " * 40}]
    for chunks in (fixed_size_chunks(pages), structure_aware_chunks(pages)):
        assert all(c["page"] == 4 for c in chunks)


def test_tiny_chunks_filtered():
    assert count_tokens(FOOTER_PAGE[0]["text"]) < MIN_CHUNK_TOKENS
    assert fixed_size_chunks(FOOTER_PAGE) == []
    assert structure_aware_chunks(FOOTER_PAGE) == []


def test_chunk_indexes_are_sequential():
    chunks = structure_aware_chunks(LONG_PAGE, chunk_tokens=100)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_unknown_strategy_rejected():
    from fastapi.testclient import TestClient

    from app.main import app

    r = TestClient(app).get("/documents/nonexistent/chunks?strategy=nope")
    assert r.status_code in (400, 404)