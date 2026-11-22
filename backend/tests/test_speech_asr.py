"""speech_asr:录音转写接口的入参校验与多提供方兜底。"""
from __future__ import annotations

import asyncio
import base64

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Route
from starlette.testclient import TestClient

import speech_asr


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(speech_asr, "require_auth", lambda request: {"uid": "u-asr"})
    monkeypatch.setattr(speech_asr.quota, "check", lambda uid: None)
    monkeypatch.setattr(speech_asr, "_limiter", speech_asr.SlidingWindowLimiter(100, 60))
    app = Starlette(routes=[
        Route("/api/speech/transcribe", speech_asr.transcribe, methods=["POST"]),
    ])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _body(data: bytes = b"RIFF0000WAVE", fmt: str = "wav") -> dict:
    return {"audio": base64.b64encode(data).decode("ascii"), "format": fmt}


def test_transcribe_returns_text(client, monkeypatch):
    async def fake(data, fmt, language):
        assert data == b"RIFF0000WAVE"
        assert fmt == "wav"
        return "x 平方加一", "zhipu", "glm-asr-2512"

    monkeypatch.setattr(speech_asr, "_transcribe", fake)
    res = client.post("/api/speech/transcribe", json=_body())
    assert res.status_code == 200, res.text
    assert res.json()["text"] == "x 平方加一"
    assert res.json()["provider"] == "zhipu"


def test_transcribe_accepts_data_uri(client, monkeypatch):
    async def fake(data, fmt, language):
        return "ok", "zhipu", "glm-asr-2512"

    monkeypatch.setattr(speech_asr, "_transcribe", fake)
    body = _body()
    body["audio"] = "data:audio/wav;base64," + body["audio"]
    assert client.post("/api/speech/transcribe", json=body).status_code == 200


def test_transcribe_rejects_invalid_base64(client):
    res = client.post("/api/speech/transcribe", json={"audio": "***", "format": "wav"})
    assert res.status_code == 400


def test_transcribe_rejects_unsupported_format(client):
    res = client.post("/api/speech/transcribe", json=_body(fmt="ogg"))
    assert res.status_code == 400


def test_transcribe_rejects_too_large(client, monkeypatch):
    monkeypatch.setattr(speech_asr, "MAX_AUDIO_BYTES", 2)
    res = client.post("/api/speech/transcribe", json=_body(b"12345"))
    assert res.status_code == 413


def test_provider_falls_back(monkeypatch):
    async def broken(*args):
        raise RuntimeError("down")

    async def ok(*args):
        return "兜底成功"

    monkeypatch.setattr(speech_asr, "_providers", lambda: [
        ("zhipu", {"base": "https://z", "key": "k", "model": "m"}),
        ("qwen", {"base": "https://q", "key": "k", "model": "m"}),
    ])
    monkeypatch.setattr(speech_asr, "_zhipu_transcribe", broken)
    monkeypatch.setattr(speech_asr, "_qwen_transcribe", ok)

    text, provider, _model = asyncio.run(speech_asr._transcribe(b"wav", "wav", "zh"))
    assert text == "兜底成功"
    assert provider == "qwen"


def test_all_providers_failed_returns_502(monkeypatch):
    async def broken(*args):
        raise RuntimeError("down")

    monkeypatch.setattr(speech_asr, "_providers", lambda: [
        ("zhipu", {"base": "https://z", "key": "k", "model": "m"}),
    ])
    monkeypatch.setattr(speech_asr, "_zhipu_transcribe", broken)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(speech_asr._transcribe(b"wav", "wav", "zh"))
    assert exc.value.status_code == 502


def test_no_provider_configured_returns_503(monkeypatch):
    monkeypatch.setattr(speech_asr, "_providers", lambda: [])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(speech_asr._transcribe(b"wav", "wav", "zh"))
    assert exc.value.status_code == 503
