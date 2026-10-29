"""公式图片识别:JSON 解析、结果清洗、接口契约(不调真实视觉模型)。"""
from __future__ import annotations

import base64
import json

import pytest

import research_vision as rv

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
       "/x8AAusB9Y9Zl9sAAAAASUVORK5CYII=")


def test_parse_json_accepts_fenced_output():
    data = rv._parse_json('```json\n{"formulas":[{"id":"f1"}]}\n```')
    assert data["formulas"][0]["id"] == "f1"


def test_clean_result_groups_and_master_validation():
    raw = {
        "formulas": [
            {"id": "f1", "target": "速度", "expr": "位移/时间",
             "variables": ["位移", "时间"], "variableMap": {"位移": "位移", "时间": "时间"}},
            {"id": "f2", "target": "加速度", "expr": "速度/时间", "variables": ["速度", "时间"]},
        ],
        "groups": [["f1"], ["f2", "missing"]],
        "master": "f2",
        "warnings": ["低置信度"],
    }
    out = rv._clean_result(raw)
    assert [f["id"] for f in out["formulas"]] == ["f1", "f2"]
    assert out["groups"] == [["f1"], ["f2"]]
    assert out["master"] == "f2"
    assert out["warnings"] == ["低置信度"]


def test_clean_result_rejects_empty():
    with pytest.raises(ValueError):
        rv._clean_result({"formulas": []})


def test_decode_image():
    mime, data = rv._decode_image({"mime": "image/png", "data": PNG})
    assert mime == "image/png" and data[:8] == b"\x89PNG\r\n\x1a\n"
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "text/plain", "data": PNG})
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "image/png", "data": "not-base64"})


def test_endpoint_with_mocked_model(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv, "extract", lambda images, columns: {
        "formulas": [{"id": "f1", "target": "速度", "expr": "位移/时间"}],
        "groups": [["f1"]], "master": None, "warnings": [],
    })
    app = Starlette(routes=[
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/formulas/extract", json={
        "images": [{"mime": "image/png", "data": PNG}],
        "columns": [{"key": "A", "label": "时间"}],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["formulas"][0]["target"] == "速度"


def test_endpoint_requires_vision_config(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision"})
    monkeypatch.setattr(rv, "is_configured", lambda: False)
    app = Starlette(routes=[
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/formulas/extract", json={
        "images": [{"mime": "image/png", "data": PNG}],
    })
    assert res.status_code == 503
