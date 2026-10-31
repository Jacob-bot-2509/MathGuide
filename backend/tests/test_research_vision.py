"""公式图片识别:JSON 解析、结果清洗、接口契约(不调真实视觉模型)。"""
from __future__ import annotations

import base64
import json

import pytest

import research_vision as rv

PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
       "/x8AAusB9Y9Zl9sAAAAASUVORK5CYII=")


def test_clean_page_result_filters_and_clamps():
    out = rv._clean_page_result({
        "blocks": [
            {"kind": "printed_formula", "latex": "v=d/t", "confidence": 1.4},
            {"kind": "handwriting", "text": "实验数据", "confidence": 0.7},
            {"kind": "unknown", "text": "drop"},
            {"kind": "figure", "text": "", "latex": ""},
        ],
        "warnings": ["模糊"],
    })
    assert [b["kind"] for b in out["blocks"]] == ["printed_formula", "handwriting"]
    assert out["blocks"][0]["confidence"] == 1.0
    assert out["warnings"] == ["模糊"]


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


def test_clean_result_keeps_handwriting_and_confidence():
    out = rv._clean_result({"formulas": [{
        "id": "f1", "target": "速度", "expr": "位移/时间",
        "variables": ["位移", "时间"], "handwriting": True, "confidence": 1.4,
    }]})
    assert out["formulas"][0]["handwriting"] is True
    assert out["formulas"][0]["confidence"] == 1.0


def test_clean_result_rejects_empty():
    with pytest.raises(ValueError):
        rv._clean_result({"formulas": []})


def test_clean_table_result_pads_and_caps():
    out = rv._clean_table_result({
        "title": "表 1",
        "columns": ["t", "x"],
        "rows": [["1", "2", "extra"], ["3"]],
        "notes": "单位:s",
        "warnings": ["轻微模糊"],
    })
    assert out["title"] == "表 1"
    assert out["columns"] == ["t", "x", "列3"]
    assert out["rows"] == [["1", "2", "extra"], ["3", "", ""]]
    assert out["notes"] == "单位:s"
    assert out["warnings"] == ["轻微模糊"]


def test_clean_table_result_uses_text_first_row_as_header():
    out = rv._clean_table_result({
        "rows": [["时间", "位移"], ["1", "2"], ["3", "4"]],
    })
    assert out["columns"] == ["时间", "位移"]
    assert out["rows"] == [["1", "2"], ["3", "4"]]


def test_clean_table_result_reads_handwriting_cells():
    out = rv._clean_table_result({
        "columns": ["t", "x"],
        "rows": [["1", "2"], ["3", "4"]],
        "handwriting": {"detected": True, "cells": [[0, 1], [1, 0]], "note": "手写"},
    })
    assert out["handwriting"]["detected"] is True
    assert out["handwriting"]["cells"] == [[0, 1], [1, 0]]
    assert out["handwriting"]["note"] == "手写"


def test_clean_table_result_rejects_empty():
    with pytest.raises(ValueError):
        rv._clean_table_result({"columns": ["a"], "rows": []})


def test_extract_table_endpoint_with_mocked_model(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    import research_papers as rp

    monkeypatch.setattr(rp, "require_auth", lambda request: {"uid": "u-vision"})
    monkeypatch.setattr(rp.rc, "_doc_row", lambda uid, doc_id: {
        "id": doc_id, "name": "paper.pdf", "pages": 5, "mime": "application/pdf",
        "status": "uploaded", "deletedAt": 0,
    })
    monkeypatch.setattr(rp.vision, "is_configured", lambda: True)
    monkeypatch.setattr(rp.vision, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rp.vision, "extract_table", lambda mime, data: {
        "title": "表 1", "columns": ["t", "x"], "rows": [["1", "2"]],
        "notes": "", "warnings": [],
    })
    app = Starlette(routes=[
        Route("/api/research/papers/{doc_id}/extract-table", rp.extract_table,
              methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/papers/doc-1/extract-table", json={
        "image": {"mime": "image/png", "data": PNG},
        "page": 3,
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["table"]["rows"] == [["1", "2"]]
    assert body["docName"] == "paper.pdf"
    assert body["page"] == 3


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

    seen: dict[str, str] = {}

    def fake_extract(images, columns, context=""):
        seen["context"] = context
        return {
            "formulas": [{"id": "f1", "target": "速度", "expr": "位移/时间"}],
            "groups": [["f1"]], "master": None, "warnings": [],
        }

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv, "extract", fake_extract)
    app = Starlette(routes=[
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/formulas/extract", json={
        "images": [{"mime": "image/png", "data": PNG}],
        "columns": [{"key": "A", "label": "时间"}],
        "text": "式中 d 为位移，t 为时间。",
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["formulas"][0]["target"] == "速度"
    assert "t 为时间" in seen["context"]


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
