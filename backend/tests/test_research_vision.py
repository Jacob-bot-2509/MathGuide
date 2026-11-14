"""公式图片识别:JSON 解析、结果清洗、接口契约(不调真实视觉模型)。"""
from __future__ import annotations

import base64
import json

import httpx
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


# ---------- G3 补充:请求体构造 / HTTP 错误映射 / 畸形响应 ----------


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _Post:
    """记录 httpx.post 的调用并返回预置响应(或抛预置异常)。"""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "headers": headers, "json": json,
                           "timeout": timeout})
        if isinstance(self.response, Exception):
            raise self.response
        return self.response

    @property
    def body(self):
        return self.calls[0]["json"]


def _configure(monkeypatch, base="https://vision.example.test/v1", key="vk",
               model="qwen3-vl"):
    monkeypatch.setenv("MG_VISION_BASE_URL", base)
    monkeypatch.setenv("MG_VISION_API_KEY", key)
    monkeypatch.setenv("MG_VISION_MODEL", model)


def _unconfigure(monkeypatch):
    for name in ("MG_VISION_BASE_URL", "MG_VISION_API_KEY", "MG_VISION_MODEL",
                 "MG_ALIYUN_BASE_URL", "MG_ALIYUN_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def _model_reply(payload):
    return _Resp(payload={"choices": [{"message": {"content": json.dumps(payload)}}]})


class _DeniedLimiter:
    def allow(self, key):
        return False


def test_cfg_falls_back_to_aliyun_env(monkeypatch):
    _unconfigure(monkeypatch)
    assert rv.is_configured() is False
    monkeypatch.setenv("MG_ALIYUN_BASE_URL", "https://aliyun.example.test/v1/")
    monkeypatch.setenv("MG_ALIYUN_API_KEY", "ak")
    cfg = rv._cfg()
    assert cfg["base"] == "https://aliyun.example.test/v1"    # 去掉尾斜杠
    assert cfg["key"] == "ak"
    assert cfg["model"] == "qwen3.8-omni-flash"
    assert rv.is_configured() is True


def test_prompt_includes_headers_and_context():
    prompt = rv._prompt([{"key": "A", "label": "时间"}, {"key": "B"}, {"label": ""}],
                        "  式中 t 为时间  ")
    assert "时间" in prompt and "B" in prompt
    assert "式中 t 为时间" in prompt
    plain = rv._prompt([])
    assert "页面文字说明" not in plain
    long_context = "x" * 9000
    assert len(rv._prompt([], long_context)) < 9000 + len(rv.SYSTEM)


def test_parse_json_rejects_non_json_and_non_object():
    with pytest.raises(ValueError):
        rv._parse_json("模型拒答:无法识别")
    with pytest.raises(ValueError):
        rv._parse_json("[1, 2, 3]")
    assert rv._parse_json('前言 {"a": 1} 结尾') == {"a": 1}


def test_clean_result_dedupes_ids_and_drops_bad_items():
    out = rv._clean_result({
        "formulas": [
            {"id": "f1", "target": "速度", "expr": "=位移/时间",
             "variables": ["位移", 1, 2.5, {"bad": True}],
             "variableMap": {"位移": "位移", 3: 4, "x": 5},
             "units": {"速度": "m/s", 1: "s", "y": None},
             "handwriting": "yes", "confidence": 1.5, "note": "n" * 400},
            "not-a-dict",
            {"id": "f1", "target": "", "expr": "x"},
            {"id": "f1", "target": "加速度", "expr": "速度/时间"},
        ],
        "groups": [["f1"], "bad", ["missing"]],
        "master": "not-an-id",
        "warnings": ["低置信度", "手写", "x", "y", "z", "w", "v", "u", "t", "s", "r"],
    })
    ids = [f["id"] for f in out["formulas"]]
    assert ids == ["f1", "f1-4"]              # 重复 id 加序号
    first = out["formulas"][0]
    assert first["expr"] == "位移/时间"        # 去掉等号
    assert first["variables"] == ["位移", "1", "2.5"]
    assert first["variableMap"] == {"位移": "位移"}   # 非 str 值被丢弃
    assert first["units"] == {"速度": "m/s", "1": "s"}
    assert first["handwriting"] is None        # 非 bool 归一为 None
    assert first["confidence"] == 1.0
    assert len(first["note"]) == 200
    assert out["groups"] == [["f1"], ["f1-4"]]  # 未覆盖的 id 各自成组
    assert out["master"] is None               # master 不在 id 集合里
    assert len(out["warnings"]) == 10


def test_clean_result_requires_usable_formulas():
    with pytest.raises(ValueError):
        rv._clean_result({"formulas": "not-a-list"})
    with pytest.raises(ValueError):
        rv._clean_result({"formulas": [{"target": "x"}, "junk"]})


def test_clean_page_result_requires_blocks():
    with pytest.raises(ValueError):
        rv._clean_page_result({"blocks": "not-a-list"})
    with pytest.raises(ValueError):
        rv._clean_page_result({"blocks": [{"kind": "unknown"}, "junk",
                                          {"kind": "figure"}]})
    out = rv._clean_page_result({"blocks": [
        {"kind": "FIGURE", "text": "图 1", "latex": "", "confidence": "bad"},
        {"kind": "figure", "latex": "x^2", "confidence": 0.4},
    ], "warnings": "not-a-list"})
    assert out["blocks"][0]["kind"] == "figure"
    assert out["blocks"][0]["confidence"] == 0.0
    assert out["blocks"][1]["latex"] == "x^2"
    assert out["warnings"] == []


def test_looks_numeric_handles_separators():
    assert rv._looks_numeric("1,234.5") is True
    assert rv._looks_numeric(" 12% ".strip()) is True
    assert rv._looks_numeric("时间") is False
    assert rv._looks_numeric("") is False


def test_decode_image_rejects_bad_items(monkeypatch):
    with pytest.raises(ValueError):
        rv._decode_image("not-a-dict")
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "application/pdf", "data": PNG})
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "image/png", "data": "@@@"})
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "image/png", "data": ""})
    mime, data = rv._decode_image({"mime": "IMAGE/PNG", "data": PNG})
    assert mime == "image/png" and data.startswith(b"\x89PNG")
    monkeypatch.setattr(rv, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(ValueError):
        rv._decode_image({"mime": "image/png", "data": PNG})


def test_call_model_builds_request_and_parses_reply(monkeypatch):
    _configure(monkeypatch)
    payload = {"formulas": [{"id": "f1", "target": "速度", "expr": "位移/时间"}],
               "groups": [["f1"]], "master": None, "warnings": []}
    post = _Post(_model_reply(payload))
    monkeypatch.setattr(rv.httpx, "post", post)

    out = rv._call_model([("image/png", b"\x89PNG-data")], [{"label": "时间"}],
                         "式中 t 指时间")
    assert out["formulas"][0]["target"] == "速度"
    call = post.calls[0]
    assert call["url"] == "https://vision.example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer vk"
    assert call["timeout"] == rv.TIMEOUT
    assert call["json"]["model"] == "qwen3-vl"
    assert call["json"]["temperature"] == 0
    content = call["json"]["messages"][0]["content"]
    assert content[0]["type"] == "text" and "时间" in content[0]["text"]
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content[1]["image_url"]["url"].endswith(
        base64.b64encode(b"\x89PNG-data").decode("ascii"))


def test_call_model_maps_http_errors_and_malformed_body(monkeypatch):
    _configure(monkeypatch)
    images = [("image/png", b"data")]

    for code in (401, 429, 500):
        monkeypatch.setattr(rv.httpx, "post",
                            _Post(_Resp(status_code=code, text="upstream says no")))
        with pytest.raises(RuntimeError) as excinfo:
            rv._call_model(images, [])
        assert str(code) in str(excinfo.value)

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(payload={"choices": []})))
    with pytest.raises(RuntimeError):
        rv._call_model(images, [])

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(payload={"choices": "bad"})))
    with pytest.raises(RuntimeError):
        rv._call_model(images, [])

    refusal = _Resp(payload={"choices": [{"message": {"content": "抱歉,我看不清这张图"}}]})
    monkeypatch.setattr(rv.httpx, "post", _Post(refusal))
    with pytest.raises(ValueError):
        rv._call_model(images, [])

    listy = _Resp(payload={"choices": [{"message": {"content": [
        {"type": "text", "text": "前言"},
        {"type": "text", "text": json.dumps({
            "formulas": [{"id": "f1", "target": "t", "expr": "a/b"}]})},
        "junk",
    ]}}]})
    monkeypatch.setattr(rv.httpx, "post", _Post(listy))
    assert rv._call_model(images, [])["formulas"][0]["target"] == "t"

    monkeypatch.setattr(rv.httpx, "post",
                        _Post(httpx.ReadTimeout("timeout talking to model")))
    with pytest.raises(httpx.HTTPError):
        rv._call_model(images, [])


def test_call_model_requires_configuration(monkeypatch):
    _unconfigure(monkeypatch)
    with pytest.raises(RuntimeError):
        rv._call_model([("image/png", b"data")], [])


def test_call_page_builds_request_and_maps_errors(monkeypatch):
    _configure(monkeypatch)
    payload = {"blocks": [{"kind": "printed_formula", "latex": "v=d/t"}],
               "warnings": []}
    post = _Post(_model_reply(payload))
    monkeypatch.setattr(rv.httpx, "post", post)

    out = rv._call_page([("image/png", b"data")], "页面里的说明文字")
    assert out["blocks"][0]["kind"] == "printed_formula"
    content = post.calls[0]["json"]["messages"][0]["content"]
    assert "页面文字(可辅助判断区块类型)" in content[0]["text"]
    assert "页面里的说明文字" in content[0]["text"]

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(status_code=403, text="forbidden")))
    with pytest.raises(RuntimeError):
        rv._call_page([("image/png", b"data")])

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(payload={})))
    with pytest.raises(RuntimeError):
        rv._call_page([("image/png", b"data")])

    bad_json = _Resp(payload={"choices": [{"message": {"content": "<html>oops</html>"}}]})
    monkeypatch.setattr(rv.httpx, "post", _Post(bad_json))
    with pytest.raises(ValueError):
        rv._call_page([("image/png", b"data")])

    _unconfigure(monkeypatch)
    with pytest.raises(RuntimeError):
        rv._call_page([("image/png", b"data")])


def test_explain_image_validates_input_and_returns_text(monkeypatch):
    with pytest.raises(ValueError):
        rv.explain_image("application/pdf", b"data", "问题")
    with pytest.raises(ValueError):
        rv.explain_image("image/png", b"", "问题")
    monkeypatch.setattr(rv, "MAX_IMAGE_BYTES", 4)
    with pytest.raises(ValueError):
        rv.explain_image("image/png", b"too-long", "问题")
    monkeypatch.undo()

    _unconfigure(monkeypatch)
    with pytest.raises(RuntimeError):
        rv.explain_image("image/png", b"data", "问题")

    _configure(monkeypatch)
    reply = _Resp(payload={"choices": [{"message": {"content": "  这是折线图  "}}]})
    post = _Post(reply)
    monkeypatch.setattr(rv.httpx, "post", post)
    assert rv.explain_image("image/png", b"data", "") == "这是折线图"
    prompt = post.calls[0]["json"]["messages"][0]["content"][0]["text"]
    assert "解释这张图表或公式的含义" in prompt      # 空问题走默认提示
    assert post.calls[0]["json"]["temperature"] == 0.2

    listy = _Resp(payload={"choices": [{"message": {"content": [
        {"text": "第一段"}, {"text": "第二段"}, {"no_text": 1}, "junk"]}}]})
    monkeypatch.setattr(rv.httpx, "post", _Post(listy))
    assert rv.explain_image("image/png", b"data", "问") == "第一段第二段"

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(status_code=429, text="slow down")))
    with pytest.raises(RuntimeError):
        rv.explain_image("image/png", b"data", "问")

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(payload={"choices": []})))
    with pytest.raises(RuntimeError):
        rv.explain_image("image/png", b"data", "问")

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(
        payload={"choices": [{"message": {"content": "y" * 5000}}]})))
    assert len(rv.explain_image("image/png", b"data", "问")) == 4000


def test_chat_text_handles_list_content_and_errors(monkeypatch):
    cfg = {"base": "https://vision.example.test/v1", "key": "vk", "model": "m"}
    listy = _Resp(payload={"choices": [{"message": {"content": [
        {"text": '{"rows": [[1]]}'}, {"no_text": True}]}}]})
    post = _Post(listy)
    monkeypatch.setattr(rv.httpx, "post", post)
    assert rv._chat_text(cfg, "转录", "image/png", b"data") == '{"rows": [[1]]}'
    assert post.calls[0]["json"]["temperature"] == 0.0

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(
        payload={"choices": [{"message": {"content": "纯文本"}}]})))
    assert rv._chat_text(cfg, "转录", "image/png", b"data") == "纯文本"

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(status_code=503, text="down")))
    with pytest.raises(RuntimeError):
        rv._chat_text(cfg, "转录", "image/png", b"data")

    monkeypatch.setattr(rv.httpx, "post", _Post(_Resp(payload={"choices": []})))
    with pytest.raises(RuntimeError):
        rv._chat_text(cfg, "转录", "image/png", b"data")


def test_extract_table_validates_and_cleans(monkeypatch):
    with pytest.raises(ValueError):
        rv.extract_table("text/plain", b"data")
    with pytest.raises(ValueError):
        rv.extract_table("image/png", b"")
    _unconfigure(monkeypatch)
    with pytest.raises(RuntimeError):
        rv.extract_table("image/png", b"data")

    _configure(monkeypatch)
    monkeypatch.setattr(rv, "_chat_text", lambda cfg, prompt, mime, data:
                        json.dumps({"title": "表 1", "columns": ["t"],
                                    "rows": [["1"]], "notes": ""}))
    out = rv.extract_table("image/png", b"data")
    assert out["title"] == "表 1"
    assert out["rows"] == [["1"]]


def test_extract_delegates_to_model_call(monkeypatch):
    seen = {}

    def fake_call(images, columns, context=""):
        seen["images"] = images
        seen["context"] = context
        return {"formulas": [{"id": "f1", "target": "t", "expr": "a/b"}]}

    monkeypatch.setattr(rv, "_call_model", fake_call)
    out = rv.extract([("image/png", b"data")], [{"label": "t"}], "上下文")
    assert out["formulas"][0]["id"] == "f1"
    assert seen["context"] == "上下文"


def test_clean_table_result_rejects_missing_rows_and_row_items():
    with pytest.raises(ValueError):
        rv._clean_table_result({"columns": ["a"]})
    with pytest.raises(ValueError):
        rv._clean_table_result({"rows": ["not-a-row", 3]})
    out = rv._clean_table_result({"rows": [[None, " 2 "], "junk"], "columns": []})
    assert out["rows"] == [["", "2"]]
    assert out["columns"] == ["列1", "列2"]
    assert out["title"] == "论文表格"


def test_clean_table_result_flags_overflow_and_handwriting():
    rows = [["1", "2"]] + [["x"] * 31]
    out = rv._clean_table_result({"rows": rows, "columns": ["a", "b"],
                                  "handwriting": {"detected": False}})
    assert any("截断" in w for w in out["warnings"])
    assert out["handwriting"]["detected"] is False

    bad_cells = rv._clean_table_result({
        "rows": [["1", "2"]], "columns": ["a", "b"],
        "handwriting": {"detected": True, "cells": [[0, "x"]], "note": "手写"}})
    assert bad_cells["handwriting"]["cells"] == []
    assert bad_cells["handwriting"]["detected"] is True
    assert any("手写" in w for w in bad_cells["warnings"])

    out_of_range = rv._clean_table_result({
        "rows": [["1", "2"]],
        "handwriting": {"cells": [[5, 0]]}})
    assert out_of_range["handwriting"]["cells"] == []

    not_list_cells = rv._clean_table_result({
        "rows": [["1", "2"]], "handwriting": {"cells": "nope"}})
    assert not_list_cells["handwriting"]["cells"] == []
    assert not_list_cells["handwriting"]["detected"] is True

    has_hw = rv._clean_table_result({"rows": [["1", "2"]], "hasHandwriting": True})
    assert has_hw["handwriting"]["detected"] is True
    assert has_hw["handwriting"]["cells"] == []

    mixed_rows = rv._clean_table_result({
        "rows": [["1", "2"], "junk"], "columns": ["a", "b"],
        "handwriting": {"detected": True, "cells": [[0, 0]]}})
    assert mixed_rows["handwriting"]["cells"] == []      # 行数据畸形 → 丢弃手写坐标


def test_analyze_page_validation_and_error_mapping(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision-page"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    app = Starlette(routes=[
        Route("/api/research/papers/analyze-page", rv.analyze_page, methods=["POST"]),
    ])
    client = TestClient(app)
    good = {"images": [{"mime": "image/png", "data": PNG}]}

    assert client.post("/api/research/papers/analyze-page", json={}).status_code == 400
    assert client.post("/api/research/papers/analyze-page",
                       json={"images": []}).status_code == 400
    too_many = {"images": [{"mime": "image/png", "data": PNG}] * (rv.MAX_IMAGES + 1)}
    assert client.post("/api/research/papers/analyze-page",
                       json=too_many).status_code == 400
    assert client.post("/api/research/papers/analyze-page",
                       json={"images": [{"mime": "application/pdf", "data": PNG}]}
                       ).status_code == 400

    monkeypatch.setattr(rv, "MAX_TOTAL_BYTES", 1)
    assert client.post("/api/research/papers/analyze-page",
                       json=good).status_code == 413
    monkeypatch.setattr(rv, "MAX_TOTAL_BYTES", 20 * 1024 * 1024)

    def raise_value(*args, **kwargs):
        raise ValueError("模型未返回 JSON")

    def raise_runtime(*args, **kwargs):
        raise RuntimeError("视觉模型返回 HTTP 500: boom")

    def raise_http(*args, **kwargs):
        raise httpx.ConnectError("down")

    for broken, expected in ((raise_value, 422), (raise_runtime, 502), (raise_http, 502)):
        monkeypatch.setattr(rv, "_call_page", broken)
        res = client.post("/api/research/papers/analyze-page", json=good)
        assert res.status_code == expected

    monkeypatch.setattr(rv, "_limiter", _DeniedLimiter())
    assert client.post("/api/research/papers/analyze-page",
                       json=good).status_code == 429
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv, "is_configured", lambda: False)
    assert client.post("/api/research/papers/analyze-page",
                       json=good).status_code == 503


def test_analyze_page_saves_blocks_and_tolerates_failures(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    calls = {"saved": 0}

    def fake_doc_row(uid, doc_id):
        calls["doc"] = (uid, doc_id)
        return {"id": doc_id, "deletedAt": 0}

    def fake_save_blocks(uid, doc_id, page, blocks):
        calls["save"] = (doc_id, page, len(blocks))
        return len(blocks)

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision-save"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv, "_call_page", lambda images, text="": {
        "blocks": [{"kind": "printed_text", "text": "正文"}], "warnings": []})
    monkeypatch.setattr(rv.rc, "_doc_row", fake_doc_row)
    monkeypatch.setattr(rv.rc, "_save_page_blocks", fake_save_blocks)

    app = Starlette(routes=[
        Route("/api/research/papers/analyze-page", rv.analyze_page, methods=["POST"]),
    ])
    client = TestClient(app)
    body = client.post("/api/research/papers/analyze-page", json={
        "images": [{"mime": "image/png", "data": PNG}],
        "docId": "doc-1",
        "page": "3",
        "text": "页面文字",
    }).json()
    assert body["saved"] == 1
    assert body["blocks"][0]["kind"] == "printed_text"
    assert calls["save"] == ("doc-1", 3, 1)

    def broken_row(uid, doc_id):
        raise RuntimeError("db down")

    def broken_save(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(rv.rc, "_doc_row", broken_row)
    monkeypatch.setattr(rv.rc, "_save_page_blocks", broken_save)
    body = client.post("/api/research/papers/analyze-page", json={
        "images": [{"mime": "image/png", "data": PNG}],
        "docId": "doc-2",
        "page": "not-a-number",
    }).json()
    assert body["saved"] == 0        # 文档校验/保存失败都不影响识别结果

    def deleted_row(uid, doc_id):
        return {"id": doc_id, "deletedAt": 1}

    monkeypatch.setattr(rv.rc, "_doc_row", deleted_row)
    body = client.post("/api/research/papers/analyze-page", json={
        "images": [{"mime": "image/png", "data": PNG}],
        "docId": "doc-3",
        "page": 1,
    }).json()
    assert body["saved"] == 0


def test_extract_formulas_validation_and_save_branches(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    calls = {}

    def fake_save_formulas(uid, doc_id, table_id, formulas):
        calls["save_formulas"] = (doc_id, table_id, len(formulas))
        return len(formulas)

    def fake_save_blocks(uid, doc_id, page, formulas):
        calls["save_blocks"] = (doc_id, page, len(formulas))
        return len(formulas) * 2

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision-form"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv, "extract", lambda images, columns, context="": {
        "formulas": [{"id": "f1", "target": "速度", "expr": "位移/时间"}],
        "groups": [["f1"]], "master": None, "warnings": []})
    monkeypatch.setattr(rv.rc, "_doc_row",
                        lambda uid, doc_id: {"id": doc_id, "deletedAt": 0})
    monkeypatch.setattr(rv.rc, "_save_extracted_formulas", fake_save_formulas)
    monkeypatch.setattr(rv.rc, "_save_source_blocks", fake_save_blocks)

    app = Starlette(routes=[
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    good = {"images": [{"mime": "image/png", "data": PNG}]}

    assert client.post("/api/research/formulas/extract", json={}).status_code == 400
    too_many = {"images": [{"mime": "image/png", "data": PNG}] * (rv.MAX_IMAGES + 1)}
    assert client.post("/api/research/formulas/extract",
                       json=too_many).status_code == 400
    monkeypatch.setattr(rv, "MAX_TOTAL_BYTES", 1)
    assert client.post("/api/research/formulas/extract", json=good).status_code == 413
    monkeypatch.setattr(rv, "MAX_TOTAL_BYTES", 20 * 1024 * 1024)

    body = client.post("/api/research/formulas/extract", json={
        **good, "docId": "doc-1", "tableId": "tbl-1", "page": "2",
        "columns": [{"key": "A", "label": "时间"}], "text": "说明"}).json()
    assert body["saved"] == 1
    assert body["blocks"] == 2
    assert calls["save_formulas"] == ("doc-1", "tbl-1", 1)
    assert calls["save_blocks"] == ("doc-1", 2, 1)

    def broken(*args, **kwargs):
        raise RuntimeError("storage down")

    monkeypatch.setattr(rv.rc, "_save_extracted_formulas", broken)
    monkeypatch.setattr(rv.rc, "_save_source_blocks", broken)
    monkeypatch.setattr(rv.rc, "_doc_row", broken)
    body = client.post("/api/research/formulas/extract", json={
        **good, "docId": "doc-2", "tableId": "tbl-2", "page": "x"}).json()
    assert body["saved"] == 0 and body["blocks"] == 0

    monkeypatch.setattr(rv.rc, "_doc_row",
                        lambda uid, doc_id: {"id": doc_id, "deletedAt": 1})
    body = client.post("/api/research/formulas/extract", json={
        **good, "docId": "doc-3", "tableId": "tbl-3"}).json()
    assert body["saved"] == 0 and body["blocks"] == 0

    monkeypatch.setattr(rv, "_limiter", _DeniedLimiter())
    assert client.post("/api/research/formulas/extract", json=good).status_code == 429


def test_extract_formulas_maps_model_errors(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision-err"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    app = Starlette(routes=[
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    good = {"images": [{"mime": "image/png", "data": PNG}]}

    def raise_value(*args, **kwargs):
        raise ValueError("模型未返回 JSON")

    def raise_runtime(*args, **kwargs):
        raise RuntimeError("视觉模型返回 HTTP 429: slow")

    def raise_http(*args, **kwargs):
        raise httpx.ReadTimeout("timeout")

    for broken, expected in ((raise_value, 422), (raise_runtime, 502), (raise_http, 502)):
        monkeypatch.setattr(rv, "extract", broken)
        res = client.post("/api/research/formulas/extract", json=good)
        assert res.status_code == expected

    assert client.post("/api/research/formulas/extract", json={
        "images": [{"mime": "image/png", "data": "@@@"}]}).status_code == 400


def test_page_call_accepts_list_content(monkeypatch):
    _configure(monkeypatch)
    post = _Post(_Resp(payload={"choices": [{"message": {"content": [
        {"text": json.dumps({"blocks": [{"kind": "figure", "text": "图注"}]})},
        {"no_text": True},
    ]}}]}))
    monkeypatch.setattr(rv.httpx, "post", post)
    out = rv._call_page([("image/png", b"data")])
    assert out["blocks"][0]["text"] == "图注"


def test_save_failures_are_logged_but_do_not_fail_recognition(monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    def broken_save(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(rv, "require_auth", lambda request: {"uid": "u-vision-save-err"})
    monkeypatch.setattr(rv, "is_configured", lambda: True)
    monkeypatch.setattr(rv, "_limiter", rv.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rv.rc, "_doc_row",
                        lambda uid, doc_id: {"id": doc_id, "deletedAt": 0})
    monkeypatch.setattr(rv.rc, "_save_page_blocks", broken_save)
    monkeypatch.setattr(rv.rc, "_save_extracted_formulas", broken_save)
    monkeypatch.setattr(rv.rc, "_save_source_blocks", broken_save)
    monkeypatch.setattr(rv, "_call_page", lambda images, text="": {
        "blocks": [{"kind": "printed_text", "text": "正文"}], "warnings": []})
    monkeypatch.setattr(rv, "extract", lambda images, columns, context="": {
        "formulas": [{"id": "f1", "target": "t", "expr": "a/b"}],
        "groups": [["f1"]], "master": None, "warnings": []})
    app = Starlette(routes=[
        Route("/api/research/papers/analyze-page", rv.analyze_page, methods=["POST"]),
        Route("/api/research/formulas/extract", rv.extract_formulas, methods=["POST"]),
    ])
    client = TestClient(app)
    payload = {"images": [{"mime": "image/png", "data": PNG}], "docId": "doc-9"}

    page = client.post("/api/research/papers/analyze-page", json=payload)
    assert page.status_code == 200
    assert page.json()["saved"] == 0            # 保存失败只记日志
    assert page.json()["blocks"][0]["kind"] == "printed_text"

    formulas = client.post("/api/research/formulas/extract", json=payload)
    assert formulas.status_code == 200
    assert formulas.json()["saved"] == 0
    assert formulas.json()["blocks"] == 0
    assert formulas.json()["formulas"][0]["id"] == "f1"

