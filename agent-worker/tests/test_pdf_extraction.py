import io
import time
from unittest.mock import patch

import pytest
from app import main as worker
from pypdf import PdfWriter


def _serve_bytes(data: bytes):
    def fake_head_object(Bucket, Key):
        return {"ContentLength": len(data)}

    def fake_download_fileobj(bucket, key, fileobj):
        fileobj.write(data)

    return fake_head_object, fake_download_fileobj


def _extract(data: bytes) -> str:
    fake_head, fake_download = _serve_bytes(data)
    with (
        patch.object(worker.s3, "head_object", side_effect=fake_head),
        patch.object(worker.s3, "download_fileobj", side_effect=fake_download),
    ):
        return worker.extract_text_from_s3_pdf("test-bucket", "doc.pdf")


def _blank_pdf_bytes(num_pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    if password:
        writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_valid_pdf_extracts_without_error():
    data = _blank_pdf_bytes(num_pages=2)

    text = _extract(data)

    assert isinstance(text, str)


def test_encrypted_pdf_is_rejected():
    data = _blank_pdf_bytes(num_pages=1, password="secret")

    with pytest.raises(ValueError):
        _extract(data)


def test_zero_page_pdf_is_rejected():
    data = _blank_pdf_bytes(num_pages=0)

    with pytest.raises(ValueError):
        _extract(data)


def test_truncated_pdf_is_rejected_as_corrupted():
    full = _blank_pdf_bytes(num_pages=1)
    truncated = full[: len(full) // 2]

    with pytest.raises(ValueError, match="corrupted"):
        _extract(truncated)


class _SlowPage:
    def extract_text(self):
        time.sleep(5)
        return "slow text"


class _SlowPdfReader:
    def __init__(self, path):
        self.is_encrypted = False
        self.pages = [_SlowPage()]


def test_extraction_timeout_interrupts_slow_parsing(monkeypatch):
    monkeypatch.setattr(worker.settings, "PDF_EXTRACTION_TIMEOUT_SECONDS", 1)
    monkeypatch.setattr(worker, "PdfReader", _SlowPdfReader)

    fake_head, fake_download = _serve_bytes(b"%PDF-1.4 fake content")

    start = time.time()
    with (
        patch.object(worker.s3, "head_object", side_effect=fake_head),
        patch.object(worker.s3, "download_fileobj", side_effect=fake_download),
        pytest.raises(ValueError, match="time limit"),
    ):
        worker.extract_text_from_s3_pdf("test-bucket", "slow.pdf")
    elapsed = time.time() - start

    # The alarm should fire at ~1s, well before the page's 5s sleep completes.
    assert elapsed < 4
