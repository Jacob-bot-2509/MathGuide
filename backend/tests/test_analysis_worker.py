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
