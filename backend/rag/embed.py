"""
Embedding 客户端(可选):向量检索升级层。

配置方式(环境变量,与 LLM 同样可选;未配置时检索走纯关键词/bigram 打分):
    MG_EMBED_BASE_URL   接口地址(阿里云百炼 compatible-mode 端点)
    MG_EMBED_API_KEY    API Key
    MG_EMBED_MODEL      embedding 模型名,默认 text-embedding-v3

启用后:全部知识片段在装载时批量向量化,结果缓存到 knowledge/.embeddings.json
(键 = 模型名 + chunk id + 正文指纹,改稿/换模型自动重算;不在当前知识库的历史键随写盘清理),
检索时与关键词打分混合排序,大幅提升"换一种说法提问"的召回率;
知识量大、语义查询多时建议启用。
"""
import hashlib
import json
import math
import os
from pathlib import Path

import httpx

CACHE_PATH = Path(__file__).resolve().parent.parent / "knowledge" / ".embeddings.json"
_BATCH = 10  # 单次 /embeddings 批量上限(阿里云百炼上限 10,实测确认)


def _key(cid: str, text: str, model: str) -> str:
    """缓存键 = 模型名 + chunk id + 正文指纹。

    正文指纹保证改稿后重算;模型名保证换 embedding 模型后不会复用旧向量
    (不同模型的向量空间不可比,维度也可能不同,复用会得到看似正常但错乱的排序)。
    只按 id 缓存会在改稿/换模型后复用旧向量,且无从察觉。
    """
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return f"{model}|{cid}:{digest}"


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
        # 配置在构造时快照:缓存键、请求体与校验必须用同一套模型名/端点,
        # 避免运行期环境变量变化造成「按 A 模型缓存、用 B 模型查询」。
        cfg = _cfg()
        self._base = cfg["base"].rstrip("/")
        self._api_key = cfg["key"]
        self._model = cfg["model"]
        self._load_cache()

    def _load_cache(self) -> None:
        def _usable(vec: object) -> bool:
            # 元素必须是有限数字:缓存被手改/写坏成 ["not-a-number"] 或 NaN 时,
            # cosine 会抛 TypeError 或产出 NaN,一路冒到 /api/chat/stream 变 500
            return (
                isinstance(vec, list) and bool(vec)
                and all(
                    isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                    for x in vec
                )
            )

        try:
            if self._cache_path.exists():
                data = json.loads(self._cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 只保留形状正确的缓存项,坏项丢弃后自动重算
                    dropped = 0
                    kept: dict[str, list[float]] = {}
                    for k, v in data.items():
                        if isinstance(k, str) and _usable(v):
                            kept[k] = v
                        else:
                            dropped += 1
                    if dropped:
                        print(f"[embed] 向量缓存有 {dropped} 条损坏记录,已丢弃并将在下次重算")
                    self._cache = kept
        except (OSError, json.JSONDecodeError):
            self._cache = {}

    def _save_cache(self) -> None:
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._cache_path.with_suffix(self._cache_path.suffix + ".tmp")
            tmp.write_text(json.dumps(self._cache), encoding="utf-8")
            tmp.replace(self._cache_path)  # 原子替换:崩溃不会留下半截 JSON
        except OSError as exc:  # noqa: BLE001 缓存写不进去不影响本次检索,但要让人知道
            print(f"[embed] 向量缓存写盘失败(下次启动会重新计费): {exc}")

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """OpenAI 兼容 /embeddings 批量接口(同步调用,启动期一次)"""
        resp = httpx.post(
            f"{self._base}/embeddings",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"model": self._model, "input": texts},
            # 超时阈值:正常 <2s。服务端慢时(实测单次 42s)超过阈值即抛超时,
            # 检索自动降级为关键词模式,绝不让用户干等(embed 失败降级链路见 index.py)。
            # 注意 httpx 单值 timeout 是"每个阶段各算",connect+read 串行会双倍,
            # 必须分段给:最坏 ≈ connect 3s + read 5s = 8s
            timeout=httpx.Timeout(connect=2.0, read=3.0, write=3.0, pool=2.0),
            # 与 rag/llm.py 同口径:计费 API 直连,不走系统代理(MITM 证书拦截)
            trust_env=False,
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        vectors = [d["embedding"] for d in data]
        if len(vectors) != len(texts):
            # 少返回/多返回都不能 zip 静默截断:否则缓存缺键,后续检索才报 KeyError
            raise ValueError(f"embedding 返回条数不匹配:请求 {len(texts)} 条,返回 {len(vectors)} 条")
        return vectors

    def embed_chunks(self, chunks: list[tuple[str, str]]) -> list[list[float]]:
        """对 (chunk_id, text) 列表返回向量;缓存命中直接复用,未命中的分批请求。
        chunks 须是当前知识库的全量片段:据此清理已删除/已改稿/换模型的历史键"""
        keys = [_key(cid, text, self._model) for cid, text in chunks]
        to_embed = [(k, text) for k, (_, text) in zip(keys, chunks) if k not in self._cache]
        for i in range(0, len(to_embed), _BATCH):
            batch = to_embed[i:i + _BATCH]
            vecs = self._embed([text for _, text in batch])
            if len(vecs) != len(batch):
                raise ValueError("embedding 返回条数与请求不一致")
            for (k, _), vec in zip(batch, vecs):
                if not isinstance(vec, list) or not vec:
                    raise ValueError("embedding 返回了空向量")
                self._cache[k] = vec
        live = set(keys)
        stale = [k for k in self._cache if k not in live]
        for k in stale:
            del self._cache[k]
        if to_embed:
            # 计费可见:新增/改稿/换模型才调接口,命中缓存的零成本
            print(f"[embed] 向量接口调用 {len(to_embed)} 条,缓存命中 {len(chunks) - len(to_embed)} 条")
        if to_embed or stale:
            self._save_cache()
        missing = [k for k in keys if k not in self._cache]
        if missing:
            raise ValueError(f"embedding 缓存缺失 {len(missing)} 条")
        return [self._cache[k] for k in keys]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    @staticmethod
    def cosine(a: list[float], b: list[float]) -> float:
        # 维度不一致说明缓存与当前模型/正文对不上:返回 0 让该向量不参与排序,
        # 而不是用 zip 静默截断出一组看似合理的错误分数。
        if not a or not b or len(a) != len(b):
            return 0.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        return dot / (na * nb) if na and nb else 0.0


__all__ = ["Embedder", "is_configured", "CACHE_PATH"]
