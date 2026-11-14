"""多文献对比表与项目报告导出。"""
from __future__ import annotations

import asyncio
import io

import pytest
from docx import Document

import research_compare as rcmp
import research_corpus as rc
import research_report as rrep
import research_tables as rt


@pytest.fixture()
def research_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    rc._indexes.clear()
    rc._index_paths.clear()
    yield tmp_path


def test_compare_endpoint_builds_rows_and_sources(research_dir, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rcmp, "require_auth", lambda request: {"uid": "u-cmp"})
    monkeypatch.setattr(rcmp.llm, "is_configured", lambda: True)
    monkeypatch.setattr(rcmp, "_limiter", rcmp.SlidingWindowLimiter(100, 60))
    monkeypatch.setattr(rcmp, "_doc_meta", lambda uid, doc_id: {
        "id": doc_id, "name": f"{doc_id}.pdf", "title": f"论文 {doc_id}",
        "authors": "A. Author", "year": 2024, "venue": "Journal", "pages": 9,
    })
    monkeypatch.setattr(rcmp, "_excerpt", lambda uid, doc_id: ("正文", 3))

    async def fake_ask(meta, text):
        return {
            "question": f"{meta['title']} 的问题",
            "method": "方法", "data": "样本 30", "results": "提升 5%",
            "limitations": "",
        }

    monkeypatch.setattr(rcmp, "_ask_doc", fake_ask)
    app = Starlette(routes=[
        Route("/api/research/literature/compare", rcmp.compare, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/literature/compare", json={"docIds": ["d1", "d2"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert len(body["rows"]) == 2
    assert body["columns"][0]["key"] == "A"
    assert body["rows"][0][0] == "论文 d1"
    assert body["rowSources"][1]["docId"] == "d2"
    assert body["rowSources"][1]["page"] == 3


def test_verify_numbers_flags_values_not_in_text():
    fields = {"data": "样本 30", "results": "提升 8.4 分,通过率 82%"}
    assert rcmp._verify_numbers(fields, "样本 30,提升 8.4 分,通过率 82%") == ""
    note = rcmp._verify_numbers(fields, "样本 30,提升 8.4 分")
    assert "82" in note and "未在原文找到" in note


def test_compare_requires_two_docs(research_dir, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rcmp, "require_auth", lambda request: {"uid": "u-cmp"})
    monkeypatch.setattr(rcmp.llm, "is_configured", lambda: True)
    app = Starlette(routes=[
        Route("/api/research/literature/compare", rcmp.compare, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/literature/compare", json={"docIds": ["d1"]})
    assert res.status_code == 400


def test_report_docx_contains_project_tables_and_stats(research_dir):
    project = rc._create_project("u-rep", "研究X")
    table = rt._create_table("u-rep", {
        "title": "测量结果",
        "columns": [
            {"key": "A", "label": "x", "type": "number"},
            {"key": "B", "label": "2x", "type": "computed"},
        ],
        "rows": [["1", ""], ["2", ""], ["3", ""]],
        "formulas": {"B": "=A2*2"},
        "source": {"docId": "d1", "docName": "论文.pdf", "page": 4},
    }, project["id"])
    project["goal"] = "验证假设"
    data = rrep._build_docx("u-rep", project, [rt._get_table("u-rep", table["id"])])
    assert data.startswith(b"PK")
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "研究目标" in text and "验证假设" in text
    assert "数据与结果" in text and "测量结果" in text
    assert "描述性统计" in text
    assert "论文.pdf" in text
    assert doc.tables and len(doc.tables[0].rows) == 4


def test_report_endpoint_returns_docx(research_dir, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    project = rc._create_project("u-rep2", "报告X")
    monkeypatch.setattr(rrep, "require_auth", lambda request: {"uid": "u-rep2"})
    app = Starlette(routes=[
        Route("/api/research/report", rrep.export_report, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/report", json={"projectId": project["id"]})
    assert res.status_code == 200, res.text
    assert res.content.startswith(b"PK")
    assert "wordprocessingml" in res.headers["content-type"]


def test_report_unknown_project_404(research_dir, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rrep, "require_auth", lambda request: {"uid": "u-rep3"})
    app = Starlette(routes=[
        Route("/api/research/report", rrep.export_report, methods=["POST"]),
    ])
    client = TestClient(app)
    res = client.post("/api/research/report", json={"projectId": "nope"})
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 追加:对比表的内部分解(解析/取元数据/取正文/数值核对)与失败口径。
# 为什么重要:这张表是"用户拿去写综述"的证据链,抽不到的字段必须留空 + 警告,
# 不能编;整篇都抽不出来要给 502,而不是给一张空表。
# ---------------------------------------------------------------------------

TEXT = """Introduction
We study spectral gaps in trapped ions.

2 Methods
The sample has 30 participants and two groups.

3 Results
Accuracy improved by 8.4 points over the baseline.
"""


@pytest.fixture()
def compare_docs(tmp_path, monkeypatch):
    """真 SQLite 语料库:元数据/正文都从库里读,不 mock _connect。"""
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    monkeypatch.setattr(rc.embed_mod, "is_configured", lambda: False)
    rc._indexes.clear()
    rc._index_paths.clear()
    yield rc
    rc._indexes.clear()
    rc._index_paths.clear()


def test_parse_json_accepts_fences_and_rejects_non_objects():
    """模型输出可能带 ```json 围栏或前后闲聊:只取第一个对象。

    拿不到 JSON 或拿到数组时必须抛 ValueError,由 _extract_one 记成"抽取失败",
    绝不能把半截字符串当字段塞进表格。
    """
    assert rcmp._parse_json('{"question": "q"}') == {"question": "q"}
    assert rcmp._parse_json('```json\n{"question": "q"}\n```') == {"question": "q"}
    assert rcmp._parse_json('好的:\n{"a": 1}\n以上。') == {"a": 1}
    with pytest.raises(ValueError):
        rcmp._parse_json("模型没给 JSON")
    with pytest.raises(ValueError):
        rcmp._parse_json('["a", "b"]')       # 不是对象
    with pytest.raises(ValueError):
        rcmp._parse_json("}{")               # 括号顺序颠倒


def test_doc_meta_reads_title_fallback_and_missing_doc(compare_docs):
    """元数据:title 缺失时回退文件名,空字段给空串,pages 缺省 1;查不到 → None。"""
    rc = compare_docs
    doc = rc._ingest("u-meta", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    meta = rcmp._doc_meta("u-meta", doc["docId"])
    assert meta["id"] == doc["docId"]
    assert meta["name"] == "paper.txt"
    # 入库时从正文首行抽到了标题,就不再退回文件名
    assert meta["title"] == "Introduction"
    assert meta["authors"] == "" and meta["venue"] == ""
    assert meta["pages"] >= 1
    assert rcmp._doc_meta("u-meta", "no-such-doc") is None


def test_extract_one_rejects_missing_doc_and_empty_body(compare_docs, monkeypatch):
    """_extract_one:文档不存在 / 正文为空都抛 ValueError(由 compare 记成失败行)。

    正文为空还去问模型,等于让模型凭空编字段。
    """
    rc = compare_docs
    doc = rc._ingest("u-empty", "empty.txt",
                     (TEXT + "\nMore body.").encode(), "text/plain",
                     status="temp", analyze=False)
    with pytest.raises(ValueError):
        asyncio.run(rcmp._extract_one("u-empty", "no-such-doc"))

    monkeypatch.setattr(rcmp, "_excerpt", lambda uid, doc_id, limit=7000: ("   ", 1))
    monkeypatch.setattr(rcmp, "_ask_doc", _boom_ask)
    with pytest.raises(ValueError):
        asyncio.run(rcmp._extract_one("u-empty", doc["docId"]))


async def _boom_ask(meta, text):
    raise AssertionError("正文为空时不该调用模型")


def test_excerpt_joins_pages_and_honours_limit(compare_docs):
    """取正文:按页序拼接并带上页码/章节头;超限截断并停止。

    正文不截断会把整篇塞进提示词,直接超模型上下文;
    页码头丢了,表格里的"第几页"就没法回溯。
    """
    rc = compare_docs
    doc = rc._ingest("u-exc", "paper.txt", TEXT.encode(), "text/plain",
                     status="temp", analyze=False)
    text, first_page = rcmp._excerpt("u-exc", doc["docId"])
    assert first_page == 1
    assert "[第 1 页" in text
    assert "spectral gaps" in text

    short, _ = rcmp._excerpt("u-exc", doc["docId"], limit=40)
    assert len(short) <= 40
    assert short.startswith("[第 1 页")

    empty, empty_page = rcmp._excerpt("u-exc", "no-such-doc")
    assert empty == "" and empty_page == 1


def test_clean_fields_truncates_and_flattens_whitespace():
    """字段清洗:换行压成空格、按 FIELD_MAX 截断、缺字段给空串。

    缺字段留空是"不编造"的落地点;换行不压平会让表格单元格错行。
    """
    cleaned = rcmp._clean_fields({
        "question": "  line one\nline two  ",
        "method": "m" * 900,
        "data": None,
    })
    assert cleaned["question"] == "line one line two"
    assert len(cleaned["method"]) == rcmp.FIELD_MAX
    assert cleaned["data"] == ""
    assert cleaned["results"] == "" and cleaned["limitations"] == ""
    assert list(cleaned) == rcmp.FIELDS


def test_ask_doc_streams_answer_and_parses_fields(monkeypatch):
    """_ask_doc 走流式接口并把分片拼起来再解析。

    非流式回退会让长文抽取等十几秒,这条盯住"分片被正确拼接"。
    """
    async def fake_stream(system, user, role="main", fallback=True, thinking=False):
        for piece in ['{"question": "研究问题",', ' "method": "方法"}']:
            yield piece

    monkeypatch.setattr(rcmp.llm, "stream_chat", fake_stream)
    meta = {"title": "论文", "authors": "A", "year": 2024, "venue": "J"}
    fields = asyncio.run(rcmp._ask_doc(meta, "正文"))
    assert fields["question"] == "研究问题"
    assert fields["method"] == "方法"
    assert fields["results"] == ""


def _compare_client(monkeypatch, uid: str, *, limiter=None):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rcmp, "require_auth", lambda request: {"uid": uid})
    monkeypatch.setattr(rcmp.llm, "is_configured", lambda: True)
    monkeypatch.setattr(rcmp, "_limiter", limiter or rcmp.SlidingWindowLimiter(100, 60))
    app = Starlette(routes=[
        Route("/api/research/literature/compare", rcmp.compare, methods=["POST"])])
    return TestClient(app)


async def _fake_extract_one(uid, doc_id):
    return (
        {"id": doc_id, "name": f"{doc_id}.pdf", "title": f"论文 {doc_id}",
         "authors": "A", "year": 2024, "venue": "J", "pages": 3},
        {"question": "q", "method": "m", "data": "", "results": "", "limitations": ""},
        {"docId": doc_id, "docName": f"论文 {doc_id}", "page": 1, "quote": "",
         "kind": "paper"},
        "",
    )


def test_compare_requires_configured_llm(compare_docs, monkeypatch):
    """未配置模型 → 503(而不是空表):用户要的是"先配置",不是"没有结果"。"""
    client = _compare_client(monkeypatch, "u-nollm")
    monkeypatch.setattr(rcmp.llm, "is_configured", lambda: False)
    res = client.post("/api/research/literature/compare", json={"docIds": ["a", "b"]})
    assert res.status_code == 503


def test_compare_rejects_missing_dirty_and_too_many_ids(compare_docs, monkeypatch):
    """入参校验:缺 docIds → 400;去重后不足 2 篇 → 400;超过上限 → 400。

    去重后再判 2 篇,否则前端发 ["d1","d1"] 也能得到一张"对比表"。
    """
    client = _compare_client(monkeypatch, "u-ids")
    assert client.post("/api/research/literature/compare", json={}).status_code == 400
    assert client.post("/api/research/literature/compare",
                       json={"docIds": "d1,d2"}).status_code == 400
    # 去重(并剔除空项)后只剩一篇
    assert client.post("/api/research/literature/compare",
                       json={"docIds": ["d1", "d1", "  ", None]}).status_code == 400
    too_many = [f"d{i}" for i in range(rcmp.MAX_DOCS + 1)]
    assert client.post("/api/research/literature/compare",
                       json={"docIds": too_many}).status_code == 400


def test_compare_rate_limited(compare_docs, monkeypatch):
    """超过频率 → 429:一次对比要跑多次模型调用,限流必须真的生效。"""
    client = _compare_client(monkeypatch, "u-rate",
                             limiter=rcmp.SlidingWindowLimiter(1, 300))
    monkeypatch.setattr(rcmp, "_extract_one", _fake_extract_one)
    assert client.post("/api/research/literature/compare",
                       json={"docIds": ["d1", "d2"]}).status_code == 200
    assert client.post("/api/research/literature/compare",
                       json={"docIds": ["d1", "d2"]}).status_code == 429


def test_compare_502_when_every_doc_fails(compare_docs, monkeypatch):
    """全部抽取失败 → 502:一张全是"抽取失败"的表没有意义,不如明确报错。"""
    client = _compare_client(monkeypatch, "u-all-fail")
    res = client.post("/api/research/literature/compare",
                      json={"docIds": ["ghost-1", "ghost-2"]})
    assert res.status_code == 502


def test_compare_partial_failure_still_returns_table(compare_docs, monkeypatch):
    """单篇失败仍出报告:失败行留空并写进 warnings,成功行照常填。

    一篇坏掉就整表 502,用户得逐个重试才知道是哪篇有问题。
    """
    rc = compare_docs
    good = rc._ingest("u-partial", "good.txt", TEXT.encode(), "text/plain",
                      status="temp", analyze=False)

    async def fake_ask(meta, text):
        return {"question": "研究问题", "method": "方法",
                "data": "样本 30", "results": "提升 8.4 分", "limitations": ""}

    monkeypatch.setattr(rcmp, "_ask_doc", fake_ask)
    client = _compare_client(monkeypatch, "u-partial")
    res = client.post("/api/research/literature/compare",
                      json={"docIds": [good["docId"], "ghost"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["title"] == "文献对比表 · 1 篇"
    assert len(body["rows"]) == 2
    ok_row, bad_row = body["rows"]
    assert ok_row[2] == "研究问题" and ok_row[5] == "提升 8.4 分"
    assert ok_row[1] == ""                      # 没有年份就留空
    assert bad_row[0] == "ghost"                # 失败行用 docId 占位
    assert bad_row[6].startswith("抽取失败")
    assert body["rowSources"][1] == {}          # 失败行没有来源
    assert any("ghost" in warning for warning in body["warnings"])
    assert [column["label"] for column in body["columns"]] == rcmp.COLUMNS
    assert body["rowLabels"][1] == "ghost"


def test_compare_flags_missing_fields_and_unverified_numbers(compare_docs, monkeypatch):
    """抽不到问题/结果时给"需人工核对";数字对不上原文时给数值警告。

    这两条是防模型编造的最后一道闸,警告必须逐篇带上论文名。
    """
    rc = compare_docs
    first = rc._ingest("u-warn", "a.txt", TEXT.encode(), "text/plain",
                       status="temp", analyze=False)
    second = rc._ingest("u-warn", "b.txt",
                        (TEXT + "\nAnother paragraph for b.").encode(),
                        "text/plain", status="temp", analyze=False)
    client = _compare_client(monkeypatch, "u-warn")
    ids = [first["docId"], second["docId"]]

    async def empty_ask(meta, text):
        # 五个字段全空(_ask_doc 的真实契约是"字段齐全但可能为空")
        return {"question": "", "method": "", "data": "",
                "results": "", "limitations": ""}

    monkeypatch.setattr(rcmp, "_ask_doc", empty_ask)
    body = client.post("/api/research/literature/compare", json={"docIds": ids}).json()
    assert body["rows"][0][2:7] == ["", "", "", "", ""]
    assert sum("正文信息不足" in warning for warning in body["warnings"]) == 2

    async def fabricated_ask(meta, text):
        return {"question": "q", "method": "m", "data": "样本 30",
                "results": "提升 99.9 分", "limitations": ""}

    monkeypatch.setattr(rcmp, "_ask_doc", fabricated_ask)
    body = client.post("/api/research/literature/compare", json={"docIds": ids}).json()
    assert body["rows"][0][7].startswith("数值")
    assert "99.9" in body["rows"][0][7]
    assert any("99.9" in warning for warning in body["warnings"])
    # 原文能对上的数字不产生警告
    assert body["rows"][0][7].count("99.9") == 1


