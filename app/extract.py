from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader

from app.config import settings


def _find_file(doc_id: str) -> Path:
    """Locate a stored file by doc_id, whatever its extension."""
    matches = list(Path(settings.upload_dir).glob(f"{doc_id}.*"))
    if not matches:
        raise HTTPException(404, f"No document with id {doc_id}.")
    return matches[0]


def extract_pages(doc_id: str) -> list[dict]:
    """Return [{'page': 1, 'text': '...'}, ...] for a stored document.

    PDFs keep real page numbers. Text and markdown files have no pages,
    so they are reported as a single page 1.
    """
    path = _find_file(doc_id)

    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:                      # skip blank or image-only pages
                pages.append({"page": i, "text": text})
        if not pages:
            raise HTTPException(
                422,
                "No extractable text found. The PDF may be scanned images, "
                "which would need OCR.",
            )
        return pages

    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        raise HTTPException(422, "Document is empty.")
    return [{"page": 1, "text": text}]