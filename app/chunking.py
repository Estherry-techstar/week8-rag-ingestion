import re

import tiktoken

from app.config import settings

_encoder = tiktoken.get_encoding(settings.tokenizer_encoding)

MIN_CHUNK_TOKENS = 20          # drop footers and page-number fragments


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


def _finalise(chunks: list[dict]) -> list[dict]:
    """Drop tiny fragments, then number the survivors."""
    kept = [c for c in chunks if c["token_count"] >= MIN_CHUNK_TOKENS]
    for i, chunk in enumerate(kept):
        chunk["chunk_index"] = i
    return kept


# --------------------------------------------------------------------
# Strategy A: fixed-size token windows with overlap
# --------------------------------------------------------------------
def fixed_size_chunks(
    pages: list[dict],
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[dict]:
    """Cut every N tokens with a sliding overlap, ignoring sentence boundaries."""
    size = chunk_tokens or settings.chunk_tokens
    overlap = overlap_tokens or settings.chunk_overlap_tokens

    if overlap >= size:
        raise ValueError("Overlap must be smaller than chunk size.")

    step = size - overlap
    chunks: list[dict] = []

    for page in pages:
        tokens = _encoder.encode(page["text"])
        start = 0
        while start < len(tokens):
            window = tokens[start : start + size]
            text = _encoder.decode(window).strip()
            if text:
                chunks.append(
                    {
                        "text": text,
                        "page": page["page"],
                        "token_count": len(window),
                        "strategy": "fixed_size",
                    }
                )
            if start + size >= len(tokens):
                break
            start += step

    return _finalise(chunks)


# --------------------------------------------------------------------
# Strategy B: structure-aware splitting
# --------------------------------------------------------------------
def _split_sentences(text: str) -> list[str]:
    """Split on sentence-ending punctuation followed by whitespace."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def _split_units(text: str, max_tokens: int) -> list[str]:
    """Break text into units no larger than max_tokens.

    Paragraphs first. A paragraph that is still too large is split into
    sentences, and a sentence that is still too large is cut by tokens
    as a last resort.
    """
    units: list[str] = []

    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if count_tokens(para) <= max_tokens:
            units.append(para)
            continue

        for sentence in _split_sentences(para):
            if count_tokens(sentence) <= max_tokens:
                units.append(sentence)
            else:
                tokens = _encoder.encode(sentence)
                for i in range(0, len(tokens), max_tokens):
                    units.append(_encoder.decode(tokens[i : i + max_tokens]).strip())

    return units


def structure_aware_chunks(
    pages: list[dict],
    chunk_tokens: int | None = None,
) -> list[dict]:
    """Pack whole paragraphs/sentences up to the target size, never cutting
    through the middle of one."""
    size = chunk_tokens or settings.chunk_tokens
    chunks: list[dict] = []

    for page in pages:
        buffer: list[str] = []
        buffer_tokens = 0

        def flush():
            nonlocal buffer, buffer_tokens
            if buffer:
                text = "\n\n".join(buffer)
                chunks.append(
                    {
                        "text": text,
                        "page": page["page"],
                        "token_count": count_tokens(text),
                        "strategy": "structure_aware",
                    }
                )
            buffer = []
            buffer_tokens = 0

        for unit in _split_units(page["text"], size):
            unit_tokens = count_tokens(unit)
            if buffer and buffer_tokens + unit_tokens > size:
                flush()
            buffer.append(unit)
            buffer_tokens += unit_tokens

        flush()

    return _finalise(chunks)