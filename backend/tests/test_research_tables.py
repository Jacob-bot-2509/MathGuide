"""实验数据表:公式引擎、模板导入、API、导出。"""
from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

import research_corpus as rc
import research_tables as rt


@pytest.fixture()
def tables(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "DATA_DIR", tmp_path / "research")
    rc._indexes.clear()
    rc._index_paths.clear()
    yield tmp_path


COLS = [
    {"key": "A", "label": "时间", "type": "number"},
    {"key": "B", "label": "位移", "type": "number"},
    {"key": "C", "label": "速度", "type": "computed"},
]


def test_column_letters_roundtrip():
    assert rt._col_to_index("A") == 0
    assert rt._col_to_index("Z") == 25
    assert rt._col_to_index("AA") == 26
    assert rt._index_to_col(0) == "A"
    assert rt._index_to_col(25) == "Z"
    assert rt._index_to_col(26) == "AA"


def test_formula_per_row_and_four_decimals():
    rows = [["1", "2"], ["3", "4"]]
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "b", "type": "number"},
         {"key": "C", "label": "c", "type": "computed"}],
        rows, {"C": "=A2/B2"})
    assert result["computed"]["C"] == ["0.5000", "0.7500"]
    assert result["errors"] == []


def test_rounding_half_up_4dp():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "b", "type": "computed"}],
        [["2"]], {"B": "=1/A2"})
    assert result["computed"]["B"] == ["0.5000"]


def test_absolute_range_is_anchored():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "total", "type": "computed"}],
        [["1"], ["2"], ["3"]], {"B": "=SUM($A$2:$A$4)"})
    assert result["computed"]["B"] == ["6.0000"] * 3


def test_relative_range_shifts_per_row():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "sum", "type": "computed"}],
        [["1"], ["2"], ["3"]], {"B": "=SUM(A2:A3)"})
    assert result["computed"]["B"][:2] == ["3.0000", "5.0000"]


def test_division_by_zero_reports_cell_error():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "b", "type": "computed"}],
        [["1"], ["0"]], {"B": "=A2/0"})
    assert result["computed"]["B"][0] == ""
    assert result["errors"][0]["row"] == 0


def test_circular_dependency_rejected():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "computed"},
         {"key": "B", "label": "b", "type": "computed"}],
        [["1"]], {"A": "=B2", "B": "=A2"})
    assert result["computed"] == {}
    assert result["errors"]


def test_exponent_guard():
    result = rt.compute(
        [{"key": "A", "label": "a", "type": "number"},
         {"key": "B", "label": "b", "type": "computed"}],
        [["9"]], {"B": "=A2^999999"})
    assert result["computed"]["B"][0] == ""
    assert "指数" in result["errors"][0]["error"]


def test_merge_labels_widths_roundtrip(tables):
    table = rt._create_table("u-1", {
        "title": "m",
        "columns": [
            {"key": "A", "label": "时间", "type": "number"},
            {"key": "B", "label": "位移", "type": "number"},
        ],
        "rows": [["1", "2"], ["3", "4"]],
        "formulas": {},
        "rowLabels": ["第一组", "第二组"],
        "merges": [{"r1": 0, "c1": 0, "r2": 1, "c2": 0}],
        "colWidths": [150, 90],
        "rowHeights": [40, 55],
    }, None)
    loaded = rt._get_table("u-1", table["id"])
    assert loaded["rowLabels"] == ["第一组", "第二组"]
    assert loaded["merges"] == [{"r1": 0, "c1": 0, "r2": 1, "c2": 0}]
    assert loaded["colWidths"] == [150, 90]
    assert loaded["rowHeights"] == [40, 55]

    headers, rows = rt._table_rows_with_computed(loaded)
    assert headers[0] == "名称" and headers[1] == "时间"
    assert rows[0][0] == "第一组"

    data = rt._export_xlsx(loaded)
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data))
    ws = wb.active
    assert "B2:B3" in {str(rng) for rng in ws.merged_cells.ranges}


def test_overlapping_merges_rejected(tables):
    with pytest.raises(ValueError):
        rt._create_table("u-1", {
            "columns": [{"key": "A"}, {"key": "B"}],
            "rows": [["", ""], ["", ""]],
            "formulas": {},
            "merges": [
                {"r1": 0, "c1": 0, "r2": 1, "c2": 0},
                {"r1": 1, "c1": 0, "r2": 1, "c2": 1},
            ],
        }, None)


def test_import_csv_and_xlsx(tables):
    csv_data = "t,x\n1,2\n3,4\n".encode("utf-8")
    table = rt._import_table("u-1", "exp.csv", csv_data, None)
    assert table["title"] == "exp"
    assert [c["key"] for c in table["columns"]] == ["A", "B"]
    assert table["rows"] == [["1", "2"], ["3", "4"]]

    wb = Workbook()
    ws = wb.active
    ws.append(["t", "x"])
    ws.append([1, 2])
    ws.append([3, 4])
    buf = io.BytesIO()
    wb.save(buf)
    table = rt._import_table("u-1", "exp.xlsx", buf.getvalue(), None)
    assert table["rows"] == [["1", "2"], ["3", "4"]]

    from docx import Document

    doc = Document()
    dt = doc.add_table(rows=2, cols=2)
    for r, values in enumerate((("t", "x"), ("5", "6"))):
        for c, value in enumerate(values):
            dt.cell(r, c).text = value
    dbuf = io.BytesIO()
    doc.save(dbuf)
    table = rt._import_table("u-1", "exp.docx", dbuf.getvalue(), None)
    assert table["rows"] == [["5", "6"]]


def test_table_api_flow(tables, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rt, "require_auth", lambda request: {"uid": "u-t"})
    app = Starlette(routes=[
        Route("/api/research/tables/import", rt.import_table, methods=["POST"]),
        Route("/api/research/tables", rt.list_tables),
        Route("/api/research/tables", rt.create_table, methods=["POST"]),
        Route("/api/research/tables/{table_id}", rt.save_table, methods=["POST"]),
        Route("/api/research/tables/{table_id}/compute", rt.compute_table, methods=["POST"]),
        Route("/api/research/tables/{table_id}/export", rt.export_table),
    ])
    client = TestClient(app)

    created = client.post("/api/research/tables", json={
        "title": "demo",
        "columns": COLS,
        "rows": [["1", "2", ""], ["3", "4", ""]],
        "formulas": {"C": "=A2/B2"},
    }).json()["table"]
    tid = created["id"]

    computed = client.post(f"/api/research/tables/{tid}/compute", json={
        "title": "demo",
        "columns": COLS,
        "rows": [["1", "2", ""], ["3", "4", ""]],
        "formulas": {"C": "=A2/B2"},
    }).json()
    assert computed["computed"]["C"] == ["0.5000", "0.7500"]

    csv_res = client.get(f"/api/research/tables/{tid}/export?format=csv")
    assert csv_res.status_code == 200
    assert "0.5000" in csv_res.text

    listed = client.get("/api/research/tables").json()["tables"]
    assert listed[0]["id"] == tid

    imported = client.post(
        "/api/research/tables/import?name=exp.csv",
        content="a,b\n1,2\n".encode("utf-8"),
        headers={"content-type": "text/csv"},
    )
    assert imported.status_code == 200
    assert imported.json()["table"]["rows"] == [["1", "2"]]


def test_print_writes_xlsx_and_opens(tables, monkeypatch):
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    monkeypatch.setattr(rt, "require_auth", lambda request: {"uid": "u-p"})
    opened: list = []
    monkeypatch.setattr(rt, "_open_in_office", lambda path: opened.append(path) or True)
    app = Starlette(routes=[
        Route("/api/research/tables/{table_id}/print", rt.print_table, methods=["POST"]),
    ])
    client = TestClient(app)
    payload = {
        "title": "打印测试",
        "columns": COLS,
        "rows": [["1", "2", ""], ["3", "4", ""]],
        "formulas": {"C": "=A2/B2"},
    }
    created = rt._create_table("u-p", payload, None)

    remote = client.post(
        f"/api/research/tables/{created['id']}/print", json=payload,
        headers={"host": "example.com"})
    assert remote.status_code == 403

    res = client.post(
        f"/api/research/tables/{created['id']}/print", json=payload,
        headers={"host": "127.0.0.1:8000"})
    assert res.status_code == 200
    body = res.json()
    assert body["opened"] is True and body["file"].endswith(".xlsx")
    assert opened and opened[0].exists()
    assert opened[0].read_bytes().startswith(b"PK")
