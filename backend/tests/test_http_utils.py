"""http_utils.py:JSON 对象解析、400 语义与请求体上限。"""
from __future__ import annotations

import asyncio

import pytest
from starlette.exceptions import HTTPException

import http_utils
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def _echo(request):
    return JSONResponse(await http_utils.read_json_object(request))


def _client() -> TestClient:
    app = Starlette(routes=[Route("/", _echo, methods=["POST"])])
    return TestClient(app, raise_server_exceptions=False)


def test_accepts_json_object():
    res = _client().post("/", json={"a": 1, "b": "中文"})
    assert res.status_code == 200
    assert res.json() == {"a": 1, "b": "中文"}


def test_invalid_json_is_400():
    res = _client().post("/", content=b"{not json", headers={"Content-Type": "application/json"})
    assert res.status_code == 400


def test_non_object_is_400():
    assert _client().post("/", json=[1, 2, 3]).status_code == 400
    assert _client().post("/", json="text").status_code == 400
    assert _client().post("/", content=b"").status_code == 400


def test_content_length_limit_is_413(monkeypatch):
    monkeypatch.setattr(http_utils, "MAX_BODY_BYTES", 32)
    res = _client().post("/", json={"a": "x" * 100})
    assert res.status_code == 413


def test_chunked_body_limit_is_413(monkeypatch):
    monkeypatch.setattr(http_utils, "MAX_BODY_BYTES", 32)

    def chunks():
        yield b'{"a":"'
        yield b"x" * 100
        yield b'"}'

    res = _client().post(
        "/", content=chunks(), headers={"Content-Type": "application/json"})
    assert res.status_code == 413


def test_explicit_max_bytes_argument():
    async def tiny(request):
        return JSONResponse(await http_utils.read_json_object(request, max_bytes=10))

    app = Starlette(routes=[Route("/tiny", tiny, methods=["POST"])])
    client = TestClient(app, raise_server_exceptions=False)
    assert client.post("/tiny", json={"a": "x" * 20}).status_code == 413
    assert client.post("/tiny", json={"a": 1}).status_code == 200


def test_absurd_content_length_is_413_not_500():
    """超长数字串不能进 int():Python 3.11+ 的位数上限会抛 ValueError。"""
    class FakeRequest:
        headers = {"content-length": "9" * 5000}

        async def stream(self):
            yield b"{}"

    with pytest.raises(HTTPException) as exc:
        asyncio.run(http_utils.read_json_object(FakeRequest()))
    assert exc.value.status_code == 413


def test_lone_surrogate_is_sanitized():
    """JSON 允许 \\ud800 转义,但后续 UTF-8 编码会抛 UnicodeEncodeError 变 500。"""
    class FakeRequest:
        headers = {"content-length": "20"}

        async def stream(self):
            yield b'{"x": "\\ud800"}'

    body = asyncio.run(http_utils.read_json_object(FakeRequest()))
    assert body["x"] and set(body["x"]) == {"�"}
    assert body["x"].encode("utf-8")  # 不再抛异常
