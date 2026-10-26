"""复审补充:跨用户缓存桶、限流淘汰、登出写放大、坏知识文件、缓存元素校验。"""
from __future__ import annotations

import asyncio
import json

import pytest
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.routing import Route
from starlette.testclient import TestClient

import auth
import doc
import http_utils
import rag
import session_cache
import store
from rate_limit import SlidingWindowLimiter


# ---------- 会话缓存:空 uid 不能退化成共享桶 ----------

def test_empty_uid_never_shares_a_cache_bucket():
    session_cache.cache_textbook("", 1, "教" * 200)
    session_cache.set_summary("", 1, "摘要明文")
    assert session_cache.get_textbook("", 1) == ""
    assert session_cache.get_textbook(None, 1) == ""
    assert session_cache.get_summary("", 1) == ""
    assert session_cache.bump_tick("", 1) == 0


def test_cache_still_isolated_by_uid():
    session_cache.cache_textbook("uid-A", 1, "A" * 200)
    assert session_cache.get_textbook("uid-A", 1) == "A" * 200
    assert session_cache.get_textbook("uid-B", 1) == ""


# ---------- 限流器:按最后活跃淘汰,且绝不淘汰当前 key ----------

def test_eviction_prefers_least_recently_active():
    limiter = SlidingWindowLimiter(max_hits=5, window=100, max_keys=2)
    assert limiter.allow("a", now=0) is True
    assert limiter.allow("b", now=1) is True
    assert limiter.allow("a", now=2) is True   # a 插入早但现在最活跃
    assert limiter.allow("c", now=3) is True   # 超容,应淘汰 b(而非插入最早的 a)
    assert "b" not in limiter._hits
    assert "a" in limiter._hits
    assert "c" in limiter._hits


def test_eviction_never_drops_the_current_key():
    limiter = SlidingWindowLimiter(max_hits=5, window=100, max_keys=1)
    assert limiter.allow("old", now=0) is True
    assert limiter.allow("current", now=1) is True
    assert "current" in limiter._hits, "当前请求的 key 被淘汰,计数会被清零"
    assert len(limiter._hits) <= 1


# ---------- 登出:伪造 token 不触发全量写盘 ----------

def test_revoke_unknown_token_does_not_write(temp_store, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "_save", lambda path, data: calls.append(path))
    assert store.revoke_token("bogus-token") is False
    assert calls == [], "伪造 token 触发了 tokens.json 全量重写(写放大)"


def test_revoke_known_token_writes_once(temp_store, monkeypatch):
    calls = []
    monkeypatch.setattr(store, "_save", lambda path, data: calls.append(path))
    store._tokens[store._token_key("real-token")] = {"uid": "u-1", "issued": 0}
    assert store.revoke_token("real-token") is True
    assert len(calls) == 1
    assert store._token_key("real-token") not in store._tokens


def test_logout_is_rate_limited(temp_store):
    auth._auth_limiter.reset()
    # 不 import main:那会加载真实 .env.local 并初始化真实 embedding。
    # 这里只挂 logout 路由,既覆盖限流又不产生任何外部副作用。
    app = Starlette(routes=[Route("/api/auth/logout", auth.logout, methods=["POST"])])
    client = TestClient(app, raise_server_exceptions=False)
    codes = [
        client.post("/api/auth/logout", headers={"Authorization": "Bearer bogus"}).status_code
        for _ in range(12)
    ]
    assert 429 in codes, "伪造 token 刷登出没有被限流: %s" % codes


# ---------- store:数据文件是合法 JSON 但不是对象 ----------

@pytest.mark.parametrize("payload", ["[]", "null", "123", '"str"'])
def test_load_non_dict_json_degrades_to_empty(tmp_path, payload):
    path = tmp_path / "data.json"
    path.write_text(payload, encoding="utf-8")
    assert store._load(path) == {}


# ---------- 知识库:坏文件只跳过,不拖垮启动 ----------

def test_load_knowledge_skips_undecodable_file(tmp_path):
    (tmp_path / "good.txt").write_text("极限 求导 基础讲义", encoding="utf-8")
    (tmp_path / "bad.txt").write_bytes("\ufeff你好".encode("utf-16"))  # 非 UTF-8
    chunks = rag.load_knowledge(tmp_path)
    assert chunks, "好文件也没有被装载"
    assert all("bad" not in c.id for c in chunks)


def test_index_or_empty_survives_broken_knowledge(monkeypatch):
    def boom(_base):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    monkeypatch.setattr(rag, "load_knowledge", boom)
    index = rag._load_index_or_empty()
    assert index.search("极限", 3) == [], "坏知识库没有降级为空索引"


# ---------- 向量缓存:坏元素不能让 cosine 抛 TypeError ----------

def test_embed_cache_drops_non_numeric_vectors(tmp_path, monkeypatch):
    import rag.embed as embed_mod
    cache = tmp_path / ".embeddings.json"
    cache.write_text(json.dumps({
        "ok": [0.1, 0.2],
        "strings": ["not-a-number"],
        "empty": [],
        "nested": [[0.1]],
    }), encoding="utf-8")
    monkeypatch.setenv("MG_EMBED_BASE_URL", "")
    monkeypatch.setenv("MG_EMBED_API_KEY", "")
    monkeypatch.setenv("MG_EMBED_MODEL", "m")
    emb = embed_mod.Embedder(cache_path=cache)
    assert emb._cache == {"ok": [0.1, 0.2]}
    # 维度不一致时按 0 分处理,不 zip 截断
    assert embed_mod.Embedder.cosine([0.1, 0.2], [0.1]) == 0.0


# ---------- 请求头:超长 content-length 不能变 500 ----------

def test_huge_content_length_returns_413():
    class FakeRequest:
        headers = {"content-length": "9" * 5000}

        async def stream(self):
            raise AssertionError("超限应在读取 body 之前就拒绝")
            yield b""  # pragma: no cover

    with pytest.raises(HTTPException) as exc:
        asyncio.run(http_utils.read_json_object(FakeRequest()))
    assert exc.value.status_code == 413


# ---------- PDF:后端自带 KaTeX 资源(只部署 backend 也能渲染公式) ----------

def test_backend_ships_its_own_katex():
    katex_dir = doc._katex_dir()
    assert (katex_dir / "katex.min.js").is_file()
    assert (katex_dir / "katex.min.css").is_file()
    assert (katex_dir / "fonts").is_dir(), "缺少字体目录,CSS 里的 fonts/ 引用会 404"
    assert katex_dir.parent.name == "backend" or "backend" in str(katex_dir), (
        "优先命中的不是后端自带目录: %s" % katex_dir)
