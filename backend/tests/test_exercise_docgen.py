"""习题集生成:按条件选卷、语言/模式控制、缺译策略与文档结构。"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import exercise_docgen
from exercises import schema
from exercises.store import ExerciseStore


def make(exercise_id: str, *, topic="analysis", languages=("zh",), type_="compute",
         difficulty=2, cross_topics=()):
    content = {}
    for lang in languages:
        if lang == "zh":
            question = f"计算第 {exercise_id} 题的定积分,并写出完整过程。"
            answer = "2"
            solution = f"第 {exercise_id} 题经过换元后得到 2,所以最终答案是 2。"
        else:
            question = f"Compute the integral in exercise {exercise_id} and show every step."
            answer = "2"
            solution = f"Exercise {exercise_id} evaluates to 2 after substitution, so the answer is 2."
        content[lang] = {"question": question, "answer": answer, "solution": solution}
    data = {
        "id": exercise_id,
        "source": {
            "name": "Test",
            "tier": "research",
            "license": "MIT",
            "url": "https://example.com/source",
            "attribution": "Test Source",
        },
        "original_language": languages[0],
        "content": content,
        "type": type_,
        "difficulty": difficulty,
        "difficulty_source": "rule",
        "primary_topic": topic,
        "topics": [topic],
        "cross_topics": list(cross_topics),
        "tag_source": "rule",
    }
    return schema.parse_exercise(data)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import db
    from starlette.routing import Route as StarletteRoute

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "mathguide.db")
    db.init()
    store = ExerciseStore([
        make("doc:zh", languages=("zh",)),
        make("doc:both", languages=("zh", "en")),
        make("doc:en", languages=("en",), topic="algebra"),
        make("doc:proof", languages=("zh",), type_="proof"),
        make("doc:taylor", languages=("zh",), cross_topics=("taylor",)),
    ], tiers=("research",))
    monkeypatch.setattr(exercise_docgen, "_store", lambda: store)
    monkeypatch.setattr(exercise_docgen, "require_auth", lambda request: {"uid": "u-1"})
    monkeypatch.setattr(exercise_docgen, "_rate_check", lambda uid: None)
    app = Starlette(routes=[
        Route("/api/doc/exercise/plan", exercise_docgen.plan, methods=["POST"]),
        Route("/api/doc/exercise", exercise_docgen.generate, methods=["POST"]),
        StarletteRoute("/api/doc/exercise/history", exercise_docgen.history_list),
        StarletteRoute("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_get),
        StarletteRoute("/api/doc/exercise/history/{doc_id}", exercise_docgen.history_delete,
                       methods=["DELETE"]),
        StarletteRoute("/api/doc/exercise/history/{doc_id}/confirm",
                       exercise_docgen.history_confirm, methods=["POST"]),
    ])
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
    db.reset_for_tests()


def test_plan_excludes_previous_batch_and_reports_reuse():
    store = ExerciseStore([make(f"e{i}") for i in range(6)], tiers=("research",))
    filters = exercise_docgen._filters({"topics": ["analysis"], "count": 3})
    first, _ = exercise_docgen._select(store, filters, "zh", False, 1)
    ids = [item.id for item in first]
    second, reused = exercise_docgen._select(store, filters, "zh", False, 2, ids)
    assert len(second) == 3
    assert reused == 0
    assert not ({item.id for item in second} & set(ids))


def test_plan_reuses_when_pool_too_small():
    store = ExerciseStore([make(f"e{i}") for i in range(3)], tiers=("research",))
    filters = exercise_docgen._filters({"topics": ["analysis"], "count": 3})
    first, _ = exercise_docgen._select(store, filters, "zh", False, 1)
    ids = [item.id for item in first]
    second, reused = exercise_docgen._select(store, filters, "zh", False, 2, ids)
    assert len(second) == 3
    assert reused == 3


def test_plan_response_contains_seed_preview_batch(client):
    response = client.post("/api/doc/exercise/plan", json={"count": 3, "lang": "zh"})
    body = response.json()

    assert isinstance(body["seed"], int)
    assert isinstance(body["batchIds"], list)
    assert len(body["preview"]) <= 3
    assert body["reusedCount"] == 0


def test_plan_reports_available_counts_by_language(client):
    response = client.post("/api/doc/exercise/plan", json={
        "topics": ["analysis"], "count": 10, "lang": "zh",
    })

    assert response.status_code == 200
    data = response.json()
    assert data["available"]["zh"] == 4
    assert data["available"]["both"] == 1
    assert data["selected"] == 4
    assert data["missing"] == 6


def test_generate_questions_mode_does_not_leak_answers(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 2, "lang": "zh", "mode": "questions",
    })

    assert response.status_code == 200
    text = _text(response.json()["document"])
    assert "计算第" in text
    assert "答案" not in text
    assert "解析" not in text


def test_generate_solutions_mode_includes_answer_and_solution(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "solutions",
    })

    assert response.status_code == 200
    text = _text(response.json()["document"])
    assert "答案" in text
    assert "解析" in text


def test_generate_both_language_includes_both_questions(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "both", "mode": "questions",
    })

    assert response.status_code == 200
    text = _text(response.json()["document"])
    assert "计算第" in text
    assert "Compute the integral" in text


def test_generate_skips_missing_translation_by_default(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["algebra"], "count": 1, "lang": "zh", "mode": "questions",
    })

    assert response.status_code == 422
    assert response.json()["error"] == "no_evidence"


def test_generate_allow_partial_keeps_original_with_marker(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["algebra"], "count": 1, "lang": "zh", "mode": "questions",
        "allowPartial": True,
    })

    assert response.status_code == 200
    text = _text(response.json()["document"])
    assert "原文" in text


def test_generate_disabled_tier_is_empty(client, monkeypatch):
    monkeypatch.setattr(exercise_docgen, "_store", lambda: ExerciseStore([], tiers=("safe",)))

    response = client.post("/api/doc/exercise", json={"count": 1, "mode": "questions"})

    assert response.status_code == 422


def _text(document):
    return "\n".join(
        paragraph
        for section in document["sections"]
        for paragraph in section.get("paragraphs", [])
    )


def test_generate_uses_requirement_in_title_and_abstract(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "questions",
        "requirement": "中值定理证明专项",
    })

    assert response.status_code == 200
    document = response.json()["document"]
    assert document["title"] == "中值定理证明专项"
    assert "中值定理证明专项" in document["abstract"]


def test_requirement_infers_type_and_difficulty(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "questions",
        "requirement": "只要证明题，基础难度",
    })

    assert response.status_code == 200
    filters = response.json()["document"]["exercise_meta"]["filters"]
    assert filters["types"] == ["proof"]
    assert filters["difficulty"] == [1, 2]


def test_requirement_infers_cross_topic(client):
    response = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "questions",
        "requirement": "泰勒展开专项",
    })

    assert response.status_code == 200
    filters = response.json()["document"]["exercise_meta"]["filters"]
    assert filters["cross_topics"] == ["taylor"]


def test_generate_returns_draft_and_confirm_promotes(client):
    generated = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "questions",
    })
    draft_id = generated.json()["draftId"]

    assert client.get("/api/doc/exercise/history").json()["items"] == []
    confirmed = client.post(f"/api/doc/exercise/history/{draft_id}/confirm")
    assert confirmed.status_code == 200
    items = client.get("/api/doc/exercise/history").json()["items"]
    assert [item["id"] for item in items] == [draft_id]

    detail = client.get(f"/api/doc/exercise/history/{draft_id}").json()
    assert detail["document"]["title"] == "习题集"


def test_history_delete_removes_entry(client):
    generated = client.post("/api/doc/exercise", json={
        "topics": ["analysis"], "count": 1, "lang": "zh", "mode": "questions",
    })
    draft_id = generated.json()["draftId"]
    client.post(f"/api/doc/exercise/history/{draft_id}/confirm")

    deleted = client.delete(f"/api/doc/exercise/history/{draft_id}")
    assert deleted.status_code == 200
    assert client.get("/api/doc/exercise/history").json()["items"] == []
    assert client.get(f"/api/doc/exercise/history/{draft_id}").status_code == 404


def test_history_confirm_unknown_id_is_404(client):
    assert client.post("/api/doc/exercise/history/nope/confirm").status_code == 404
