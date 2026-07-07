"""
Tests for PDF support in /api/extract_text.

The endpoint routes .pdf uploads to the paper2md service (_pdf_to_text) and
everything else to the local ingest_bytes. paper2md is faked here so the tests
run offline; a real network probe lives at the bottom, opt-in via RUN_LIVE_PAPER2MD=1.
"""
import os

os.environ.setdefault("JWT_SECRET", "test-secret-value-at-least-32-chars-long!!")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-ant-test")

import httpx
import pytest
from fastapi.testclient import TestClient

import main
from auth import get_current_user


class _FakeUser:
    id = 1
    is_active = True
    def has_permission(self, slug):  # pipeline gate passes
        return True


class _FakeResponse:
    def __init__(self, status_code, *, text="", payload=None):
        self.status_code = status_code
        self.text = text
        self._payload = payload
    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _fake_client(response=None, exc=None):
    """Return a class usable as `httpx.AsyncClient` that yields `response`
    from .post (or raises `exc`), recording that it was called."""
    calls = {"n": 0}

    class _Client:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, *a, **k):
            calls["n"] += 1
            if exc is not None:
                raise exc
            return response

    return _Client, calls


@pytest.fixture
def client():
    main.app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(get_current_user, None)


def _upload(client, name, body, content_type):
    return client.post("/api/extract_text", files={"file": (name, body, content_type)})


def test_pdf_happy_path(client, monkeypatch):
    Client, calls = _fake_client(_FakeResponse(200, text="clean body text"))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "paper.pdf", b"%PDF-1.7 fake", "application/pdf")
    assert r.status_code == 200
    assert r.json() == {"text": "clean body text", "filename": "paper.pdf"}
    assert calls["n"] == 1


def test_pdf_service_busy_returns_503(client, monkeypatch):
    Client, _ = _fake_client(_FakeResponse(503, text="busy"))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "paper.pdf", b"%PDF", "application/pdf")
    assert r.status_code == 503
    assert "busy" in r.json()["detail"].lower()


def test_pdf_error_detail_propagates_as_502(client, monkeypatch):
    Client, _ = _fake_client(_FakeResponse(422, payload={"detail": "not a born-digital PDF"}))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "scan.pdf", b"%PDF", "application/pdf")
    assert r.status_code == 502
    assert "not a born-digital PDF" in r.json()["detail"]


def test_pdf_timeout_returns_504(client, monkeypatch):
    Client, _ = _fake_client(exc=httpx.TimeoutException("slow"))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "paper.pdf", b"%PDF", "application/pdf")
    assert r.status_code == 504


def test_pdf_unreachable_returns_502(client, monkeypatch):
    Client, _ = _fake_client(exc=httpx.ConnectError("down"))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "paper.pdf", b"%PDF", "application/pdf")
    assert r.status_code == 502


def test_txt_does_not_hit_paper2md(client, monkeypatch):
    Client, calls = _fake_client(_FakeResponse(200, text="should not be used"))
    monkeypatch.setattr(httpx, "AsyncClient", Client)
    r = _upload(client, "notes.txt", b"hello world", "text/plain")
    assert r.status_code == 200
    assert "hello world" in r.json()["text"]
    assert calls["n"] == 0  # local ingest, no paper2md call


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_PAPER2MD") != "1",
    reason="live network probe; set RUN_LIVE_PAPER2MD=1 and PAPER2MD_API_KEY to run",
)
def test_live_paper2md_probe():
    """Round-trips a real PDF through the real service. Requires a valid key in
    PAPER2MD_API_KEY (never committed) and network access."""
    import asyncio
    from pathlib import Path

    pdfs = list((Path(__file__).parent).glob("**/*.pdf"))
    assert pdfs, "no sample PDF available for the live probe"
    content = pdfs[0].read_bytes()
    text = asyncio.run(main._pdf_to_text(content, pdfs[0].name))
    assert isinstance(text, str) and len(text) > 200
