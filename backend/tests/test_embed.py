"""rag/embed.py:模型隔离的缓存键、返回条数校验、维度保护与原子写盘。"""
from __future__ import annotations

import json

import pytest

from rag import embed


def _make(tmp_path, monkeypatch, model: str = "model-a") -> embed.Embedder:
    monkeypatch.setenv("MG_EMBED_BASE_URL", "https://embed.invalid/v1")
    monkeypatch.setenv("MG_EMBED_API_KEY", "test-key")
    monkeypatch.setenv("MG_EMBED_MODEL", model)
    return embed.Embedder(tmp_path / "cache.json")


def test_cache_key_includes_model():
    assert embed._key("c1", "same text", "model-a") != embed._key("c1", "same text", "model-b")
    assert embed._key("c1", "a", "m") != embed._key("c1", "b", "m")


def test_embed_chunks_caches_and_writes_atomically(tmp_path, monkeypatch):
    emb = _make(tmp_path, monkeypatch)
    monkeypatch.setattr(emb, "_embed", lambda texts: [[1.0, 2.0] for _ in texts])

    vectors = emb.embed_chunks([("c1", "hello"), ("c2", "world")])
    assert vectors == [[1.0, 2.0], [1.0, 2.0]]
    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert len(cache) == 2
    assert all(key.startswith("model-a|") for key in cache)
    assert not (tmp_path / "cache.json.tmp").exists()


def test_changing_model_does_not_reuse_old_vectors(tmp_path, monkeypatch):
    emb = _make(tmp_path, monkeypatch, "model-a")
    monkeypatch.setattr(emb, "_embed", lambda texts: [[1.0] for _ in texts])
    emb.embed_chunks([("c1", "hello")])

    emb2 = _make(tmp_path, monkeypatch, "model-b")
    monkeypatch.setattr(emb2, "_embed", lambda texts: [[2.0] for _ in texts])
    emb2.embed_chunks([("c1", "hello")])

    cache = json.loads((tmp_path / "cache.json").read_text(encoding="utf-8"))
    assert len(cache) == 1
    assert next(iter(cache)).startswith("model-b|")


def test_short_embedding_response_raises(tmp_path, monkeypatch):
    emb = _make(tmp_path, monkeypatch)
    monkeypatch.setattr(emb, "_embed", lambda texts: [])
    with pytest.raises(ValueError):
        emb.embed_chunks([("c1", "hello")])


def test_empty_vector_raises(tmp_path, monkeypatch):
    emb = _make(tmp_path, monkeypatch)
    monkeypatch.setattr(emb, "_embed", lambda texts: [[] for _ in texts])
    with pytest.raises(ValueError):
        emb.embed_chunks([("c1", "hello")])


def test_cosine_rejects_dimension_mismatch():
    assert embed.Embedder.cosine([1.0, 2.0], [1.0, 2.0]) == pytest.approx(1.0)
    assert embed.Embedder.cosine([1.0, 2.0], [1.0, 2.0, 3.0]) == 0.0
    assert embed.Embedder.cosine([], [1.0]) == 0.0


def test_load_cache_drops_malformed_entries(tmp_path, monkeypatch):
    path = tmp_path / "cache.json"
    path.write_text(
        json.dumps({"ok": [1.0], "bad": "x", "empty": [], "strvec": ["x"]}),
        encoding="utf-8",
    )
    # NaN 也是非法缓存值(JSON 标准不允许,但 Python 的 json 默认能读)
    path.write_text(
        path.read_text(encoding="utf-8").replace("}", ', "nan": [NaN]}', 1),
        encoding="utf-8",
    )
    monkeypatch.setenv("MG_EMBED_BASE_URL", "https://embed.invalid/v1")
    monkeypatch.setenv("MG_EMBED_API_KEY", "k")
    monkeypatch.setenv("MG_EMBED_MODEL", "m")
    emb = embed.Embedder(path)
    assert emb._cache == {"ok": [1.0]}


def test_embed_query_uses_single_vector(tmp_path, monkeypatch):
    emb = _make(tmp_path, monkeypatch)
    calls: list[list[str]] = []

    def fake(texts):
        calls.append(texts)
        return [[3.0, 4.0] for _ in texts]

    monkeypatch.setattr(emb, "_embed", fake)
    assert emb.embed_query("query") == [3.0, 4.0]
    assert calls == [["query"]]
