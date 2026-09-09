"""
Embedding 客户端(可选):向量检索升级层。

配置方式(环境变量,与 LLM 同样可选;未配置时检索走纯关键词/bigram 打分):
    MG_EMBED_BASE_URL   接口地址(阿里云百炼 compatible-mode 端点)
    MG_EMBED_API_KEY    API Key
    MG_EMBED_MODEL      embedding 模型名,默认 text-embedding-v3

启用后:全部知识片段在装载时批量向量化,结果缓存到 knowledge/.embeddings.json
(以 chunk id 为键,文档内容变化自动重算),检索时与关键词打分混合排序,
大幅提升"换一种说法提问"的召回率;知识量大、语义查询多时建议启用。
"""
import json
import math
import os
from pathlib import Path

import httpx

CACHE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / ".embeddings.json"
_BATCH = 10  # 单次 /embeddings 批量上限(阿里云百炼上限 10,实测确认)


def _cfg() -> dict:
    """惰性读取配置(config.load_env 在 main 启动时执行,晚于模块导入)"""
    return {
        "base": os.getenv("MG_EMBED_BASE_URL", ""),
        "key": os.getenv("MG_EMBED_API_KEY", ""),
        "model": os.getenv("MG_EMBED_MODEL", "text-embedding-v3"),
    }


def is_configured() -> bool:
    c = _cfg()
    return bool(c["base"] and c["key"])


def model_name() -> str:
    return _cfg()["model"]


class Embedder:
    """片段向量化 + 缓存;query 向量只算一次,片段向量落盘复用"""

    def __init__(self, cache_path: Path = CACHE_PATH):
        self._cache_path = cache_path
        self._cache: dict[str, list[float]] = {}
        self._load_cache()

    def _load_cache(self) -> None:
        try:
            if self._cache_path.exists():
                self._cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.write_text(json.dumps(self._cache), encoding="utf-8")
        except OSError:
            pass

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """OpenAI 兼容 /embeddings 批量接口(同步调用,启动期一次)"""
        c = _cfg()
        resp = httpx.post(
            f"{c['base'].rstrip('/')}/embeddings",
            headers={"Authorization": f"Bearer {c['key']}"},
            json={"model": c["model"], "input": texts},
            timeout=120,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]

    def embed_chunks(self, chunks: list[tuple[str, str]]) -> list[list[float]]:
        """对 (chunk_id, text) 列表返回向量;缓存命中直接复用,未命中的分批请求"""
        to_embed = [(cid, text) for cid, text in chunks if cid not in self._cache]
        for i in range(0, len(to_embed), _BATCH):
            batch = to_embed[i:i + _BATCH]
            vecs = self._embed([text for _, text in batch])
            for (cid, _), vec in zip(batch, vecs):
                self._cache[cid] = vec
        if to_embed:
            self._save_cache()
        return [self._cache[cid] for cid, _ in chunks]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


__all__ = ["Embedder", "is_configured", "CACHE_PATH"]
