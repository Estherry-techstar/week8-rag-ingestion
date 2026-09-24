import uuid
from pathlib import Path

import filetype
from fastapi import APIRouter, File, HTTPException, UploadFile

from app.config import settings

router = APIRouter()

CHUNK = 1024 * 1024  # read 1 MB at a time
TEXT_EXTS = {".txt", ".md"}


def _detect_type(head: bytes, filename: str) -> str:
    """Identify the file from its content. Plain text has no signature,
    so fall back to the extension only for .txt and .md."""
    kind = filetype.guess(head)
    if kind and kind.extension == "pdf":
        return "pdf"
    ext = Path(filename or "").suffix.lower()
    if ext in TEXT_EXTS:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(400, "File is not valid UTF-8 text.")
        return ext.lstrip(".")
    raise HTTPException(400, "Unsupported file type. Allowed: pdf, txt, md.")


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    max_bytes = settings.max_upload_mb * 1024 * 1024

    head = await file.read(2048)
    if not head:
        raise HTTPException(400, "Empty file.")

    file_type = _detect_type(head, file.filename)
    if file_type not in settings.allowed_types:
        raise HTTPException(400, f"Type '{file_type}' is not allowed.")

    doc_id = uuid.uuid4().hex
    dest_dir = Path(settings.upload_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{doc_id}.{file_type}"

    size = len(head)
    with dest.open("wb") as out:
        out.write(head)
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > max_bytes:
                out.close()
                dest.unlink(missing_ok=True)   # don't keep the partial file
                raise HTTPException(
                    413, f"File exceeds {settings.max_upload_mb} MB limit."
                )
            out.write(chunk)

    return {
        "doc_id": doc_id,
        "original_filename": file.filename,
        "stored_as": dest.name,
        "type": file_type,
        "size_bytes": size,
    }