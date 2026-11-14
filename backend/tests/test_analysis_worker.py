import json

from analysis_worker import handle_request


def test_worker_rejects_unknown_op():
    response = handle_request({"id": "1", "op": "eval", "payload": {}})
    assert response["ok"] is False
    assert response["error"]["code"] == "unsupported_op"


def test_worker_rejects_missing_id():
    response = handle_request({"op": "ping", "payload": {}})
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_request"


def test_worker_ping():
    response = handle_request({"id": "1", "op": "ping", "payload": {}})
    assert response == {"id": "1", "ok": True, "result": {"pong": True}}


# ---------- v1.26.0 覆盖率补充:能力查询、校验拒绝与主循环容错 ----------

def test_worker_rejects_non_object_request():
    assert handle_request("nope")["error"]["code"] == "bad_request"


def test_worker_capabilities_reports_packs():
    response = handle_request({"id": "2", "op": "capabilities", "payload": {}})
    assert response["ok"] is True
    assert isinstance(response["result"], dict)


def test_worker_surfaces_validation_error_code():
    """回归参数非法时,错误码直接给前端看(bad_column),而不是 500。"""
    response = handle_request({
        "id": "3", "op": "regression",
        "payload": {"columns": [{"key": "X"}, {"key": "Y"}], "rows": [["1", "2"]],
                    "formulas": {}, "spec": {"x": ["NOPE"], "y": "Y", "model": "ols"}},
    })
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_column"


def test_main_loop_skips_blanks_and_survives_bad_lines(monkeypatch):
    """主循环:空行跳过、坏 JSON 回 bad_request、单条请求炸了也不能杀掉 worker。"""
    import io

    import analysis_worker as worker

    stdin = io.StringIO(
        "\n"
        '{"id": "a", "op": "ping"}\n'
        "not json\n"
        '{"id": "b", "op": "boom"}\n'
    )
    stdout = io.StringIO()
    monkeypatch.setattr(worker.sys, "stdin", stdin)
    monkeypatch.setattr(worker.sys, "stdout", stdout)

    def fake_handle(request):
        if request.get("op") == "boom":
            raise RuntimeError("kaboom")
        return {"id": request["id"], "ok": True, "result": {"pong": True}}

    monkeypatch.setattr(worker, "handle_request", fake_handle)
    worker.main()

    replies = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [reply["id"] for reply in replies] == ["a", "", "b"]
    assert replies[1]["error"]["code"] == "bad_request"
    assert replies[2]["error"] == {"code": "internal_error", "message": "RuntimeError"}
