"""评测运行器:走生产链路,记录检索片段、回答、元信息与延迟。

检索评测直接调 rag.search;回答评测调 chat._route_chat(与 /api/chat/stream
同一套业务路由,绕过认证/限流)。研究型问题默认跳过,避免评测依赖外部网络。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Iterable

import rag
import chat as chat_module
from rag import route as rag_route

from . import judges
from .extract import objective_check
from .types import AnswerTrace, ChunkTrace, EvalItem

_META_RE = re.compile(r"\s*\[是\]\(cmd://nb/yes\).*$", re.DOTALL)
_REVIEW_RE = re.compile(r"\n\n>\s*🔍\s*复核.*$", re.DOTALL)
_DEGRADED_MARKERS = ("⚠ 模型调用失败", "模型连接中断", "⚠ 模型连接中断")


def _clean_answer(text: str) -> str:
    """去掉问题记录按钮和复核行,避免它们进入判分上下文。"""
    text = _META_RE.sub("", text)
    text = _REVIEW_RE.sub("", text)
    return text.strip()


def _chunk_trace(chunks: list[tuple[rag.Chunk, float]]) -> list[ChunkTrace]:
    return [
        ChunkTrace(id=c.id, title=c.title, section=c.section, score=round(float(s), 4), text=c.text)
        for c, s in chunks
    ]


def _consume_stream_async(resp):
    """消费 _route_chat 返回的 SSE,拆出正文与 mg_meta。"""
    async def collect() -> tuple[str, dict]:
        text: list[str] = []
        meta: dict = {}
        async for frame in resp.body_iterator:
            raw = frame if isinstance(frame, str) else frame.decode("utf-8", "ignore")
            for line in raw.splitlines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                try:
                    value = json.loads(payload)
                except json.JSONDecodeError:
                    text.append(payload)
                    continue
                if isinstance(value, str):
                    text.append(value)
                elif isinstance(value, dict) and isinstance(value.get("mg_meta"), dict):
                    meta.update(value["mg_meta"])
        return "".join(text), meta
    return collect()


def _with_search_capture():
    """返回 (capture, restore)。capture 是 list,记录链路内所有 search 结果。"""
    original = rag.search
    captured: list[list[tuple[rag.Chunk, float]]] = []

    def wrapper(query: str, top_k: int = 3):
        result = original(query, top_k)
        captured.append(result)
        return result

    rag.search = wrapper  # type: ignore[assignment]

    def restore() -> None:
        rag.search = original  # type: ignore[assignment]

    return captured, restore


async def run_retrieval(item: EvalItem, top_k: int = 3) -> AnswerTrace:
    t0 = time.monotonic()
    try:
        chunks = await asyncio.to_thread(rag.search, item.question, top_k)
        return AnswerTrace(text="", chunks=_chunk_trace(chunks),
                           latency_s=time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001
        return AnswerTrace(error=f"{type(exc).__name__}: {exc}",
                           latency_s=time.monotonic() - t0)


_ANSWER_LOCK = asyncio.Lock()  # rag.search 捕获是全进程 monkeypatch,回答阶段串行防串台


async def run_answer(item: EvalItem, top_k: int = 3,
                     skip_research: bool = True) -> AnswerTrace:
    if skip_research and rag_route.is_research_intent(item.question):
        return AnswerTrace(error="research intent skipped in eval")
    async with _ANSWER_LOCK:
        captured, restore = _with_search_capture()
        t0 = time.monotonic()
        try:
            resp = await chat_module._route_chat(
                item.question, None, {}, {"uid": "eval", "nickname": "eval"}, {})
            text, meta = await asyncio.wait_for(_consume_stream_async(resp), timeout=300)
        except Exception as exc:  # noqa: BLE001
            return AnswerTrace(error=f"{type(exc).__name__}: {exc}",
                               latency_s=time.monotonic() - t0)
        finally:
            restore()
    chunks = captured[-1] if captured else []
    text = _clean_answer(text)
    return AnswerTrace(
        text=text,
        meta=meta,
        chunks=_chunk_trace(chunks),
        latency_s=time.monotonic() - t0,
        degraded=any(m in text for m in _DEGRADED_MARKERS),
    )


async def run_item(item: EvalItem, *, stage: str = "all", top_k: int = 3,
                   judge_role: str = "backup", use_judge: bool = True,
                   skip_research: bool = True) -> dict:
    """跑一条样本,返回可直接写 JSONL 的扁平记录。"""
    record: dict = {
        "id": item.id,
        "question": item.question,
        "domain": item.domain,
        "difficulty": item.difficulty,
        "answer_type": item.answer_type,
        "answerable": item.answerable,
        "gold_chunk_ids": item.gold_chunk_ids,
        "reference_answer": item.reference_answer,
    }
    if stage == "retrieval":
        # 只测检索:单独跑一次 search,不生成、不评审
        retrieval = await run_retrieval(item, top_k)
        record["retrieval"] = {
            "chunks": [c.__dict__ for c in retrieval.chunks],
            "latency_s": round(retrieval.latency_s, 3),
            "error": retrieval.error,
        }
        if retrieval.error:
            record["error"] = retrieval.error
        return record

    answer = await run_answer(item, top_k, skip_research)
    record["answer"] = answer.text
    record["meta"] = answer.meta
    record["latency_s"] = round(answer.latency_s, 3)
    record["degraded"] = answer.degraded
    record["retrieval"] = {
        "chunks": [c.__dict__ for c in answer.chunks],
        "latency_s": round(answer.latency_s, 3),
    }
    if answer.error:
        record["error"] = answer.error
        return record

    objective, detail = objective_check(item, answer.text)
    record["objective_correct"] = objective
    record["objective_detail"] = detail

    if use_judge:
        record["judge"] = await judges.judge_answer(item, answer.text, answer.chunks, judge_role)
    return record


async def run_items(items: Iterable[EvalItem], *, stage: str = "all", top_k: int = 3,
                    judge_role: str = "backup", use_judge: bool = True,
                    concurrency: int = 2, skip_research: bool = True,
                    on_done=None) -> list[dict]:
    sem = asyncio.Semaphore(max(1, concurrency))
    results: list[dict] = []

    async def one(item: EvalItem) -> dict:
        async with sem:
            rec = await run_item(item, stage=stage, top_k=top_k, judge_role=judge_role,
                                 use_judge=use_judge, skip_research=skip_research)
            if on_done:
                on_done(rec)
            return rec

    tasks = [asyncio.create_task(one(i)) for i in items]
    for task in asyncio.as_completed(tasks):
        results.append(await task)
    order = {item.id: idx for idx, item in enumerate(items)}
    results.sort(key=lambda r: order.get(r["id"], 999999))
    return results
