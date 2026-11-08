"""dashboard_data:只读汇总查询。"""
from __future__ import annotations

import dashboard_data
import diagnosis
import store
import usage


def _user(uid: str) -> dict:
    return {
        "uid": uid, "phone": None, "password_hash": None,
        "authMethod": "wechat", "nickname": uid, "avatar": "preset:sum",
        "createdAt": "2026-01-01T00:00:00",
    }


def test_empty_overview(temp_store):
    summary = dashboard_data.overview()
    assert summary == {
        "users": 0, "guests": 0, "tokens": 0,
        "usage_calls": 0, "usage_chars": 0, "roles": {}, "workspaces": {},
        "diagnoses": 0, "weak": 0,
    }


def test_overview_counts(temp_store):
    store.create_user(_user("u-1"))
    store.create_user(_user("guest-a"))
    store.issue_token("u-1")
    usage.record(uid="u-1", cmd="", prompt_len=1, reply_len=10,
                 role="main", research=False, ts=1.0)
    usage.record(uid="u-1", cmd="", prompt_len=2, reply_len=5,
                 role="deep", research=True, ts=2.0, workspace="research")
    diagnosis.record("u-1", "set-map", 2, "薄弱", source="self")
    diagnosis.record("u-1", "chain-rule", 4, "已掌握", source="self")

    summary = dashboard_data.overview()
    assert summary["users"] == 2
    assert summary["guests"] == 1
    assert summary["tokens"] == 1
    assert summary["usage_calls"] == 2
    assert summary["usage_chars"] == 15
    assert summary["roles"] == {"main": 1, "deep": 1}
    assert summary["workspaces"] == {"learn": 1, "research": 1}
    assert summary["diagnoses"] == 2
    assert summary["weak"] == 1


def test_weak_points_uses_latest_and_filters(temp_store):
    diagnosis.record("u-1", "set-map", 1, "很差", source="self")
    diagnosis.record("u-1", "set-map", 4, "后来会了", source="self")
    diagnosis.record("u-1", "derivative-def", 2, "薄弱", source="self")
    diagnosis.record("u-2", "chain-rule", 1, "薄弱", source="self")

    rows = dashboard_data.weak_points(limit=5)
    assert {row["pointId"] for row in rows} == {"derivative-def", "chain-rule"}
    assert rows[0]["score"] <= rows[-1]["score"]
