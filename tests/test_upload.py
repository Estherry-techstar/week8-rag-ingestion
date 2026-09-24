import io

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app

client = TestClient(app)

PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@pytest.fixture(autouse=True)
def temp_upload_dir(tmp_path, monkeypatch):
    """Keep test uploads out of the real data directory."""
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path))


def _post(filename: str, content: bytes):
    return client.post(
        "/upload", files={"file": (filename, io.BytesIO(content), "application/pdf")}
    )


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_accepts_text_file():
    r = _post("notes.txt", b"Some real text content for the pipeline.")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "txt"
    # the user's filename must not be reused on disk
    assert body["stored_as"] != "notes.txt"
    assert body["stored_as"].startswith(body["doc_id"])


def test_rejects_disguised_file():
    """A PNG renamed to .pdf is rejected on content, not extension."""
    r = _post("definitely_a.pdf", PNG_MAGIC)
    assert r.status_code == 400


def test_rejects_empty_file():
    assert _post("empty.txt", b"").status_code == 400


def test_rejects_unsupported_extension():
    assert _post("script.exe", b"MZ\x90\x00binary").status_code == 400


def test_rejects_oversized_file(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 1)
    r = _post("big.txt", b"x" * (2 * 1024 * 1024))
    assert r.status_code == 413