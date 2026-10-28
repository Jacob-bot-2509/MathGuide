"""学习掌握度诊断:LLM 评分、按账号持久化与薄弱点报告。

诊断记录追加到 data/diagnoses.jsonl(只存 uid,不存手机号/昵称),
与 usage.jsonl 同一套隐私口径:导出、注销时按 uid 读取或删除。

评分口径:1~5 分,低于 WEAK_THRESHOLD 记为薄弱点。模型输出必须为
{"score": 1-5, "comment": "..."};解析失败按服务不可用处理,不写脏数据。
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import auth
import http_utils
import rag.llm
from knowledge_graph import KnowledgeGraph, KnowledgePoint, load_graph

DATA_DIR = Path(__file__).resolve().parent / "data"
PATH = DATA_DIR / "diagnoses.jsonl"
WEAK_THRESHOLD = 3
MAX_ANSWER_CHARS = 2000
MAX_COMMENT_CHARS = 200
MAX_BODY_BYTES = 64 * 1024
_lock = threading.Lock()

SOURCES = ("llm", "self")

_JSON_OBJECT = re.compile(r"\{.*\}", re.S)
_graph: KnowledgeGraph | None = None


class DiagnosisError(ValueError):
    """模型输出无法解析为诊断结果。"""


class DiagnosisUnavailable(RuntimeError):
    """诊断依赖的模型不可用或输出不可信。"""


def get_graph() -> KnowledgeGraph:
    """进程内单例;知识图谱 CSV 很小,首次使用时加载。"""
    global _graph
    if _graph is None:
        _graph = load_graph()
    return _graph


def parse_result(text: str) -> tuple[int, str]:
    """从模型输出提取 (score, comment);允许前后缀与 ```json 围栏。"""
    raw = (text or "").strip()
    match = _JSON_OBJECT.search(raw)
    if not match:
        raise DiagnosisError("模型输出不含 JSON")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise DiagnosisError(f"模型输出不是合法 JSON: {exc}") from None
    if not isinstance(data, dict):
        raise DiagnosisError("模型输出必须是 JSON 对象")

    try:
        score = int(round(float(data.get("score"))))
    except (TypeError, ValueError, OverflowError):
        raise DiagnosisError(f"score 不是数字: {data.get('score')!r}") from None
    # 模型偶尔给出 0 或 6 分:夹到合法区间,不因越界丢掉整次诊断
    score = max(1, min(5, score))

    comment = data.get("comment")
    comment = comment.strip() if isinstance(comment, str) else ""
    return score, comment[:MAX_COMMENT_CHARS]


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def record(uid: str, point_id: str, score: int, comment: str,
           *, source: str = "llm") -> dict:
    """追加一条诊断记录,返回落盘条目。"""
    if not uid or not point_id:
        raise ValueError("uid 与 point_id 不能为空")
    if not isinstance(score, int) or not 1 <= score <= 5:
        raise ValueError("score 必须是 1~5 的整数")
    if source not in SOURCES:
        raise ValueError(f"source 非法: {source}")
    entry = {
        "uid": uid,
        "pointId": point_id,
        "score": score,
        "comment": (comment or "")[:MAX_COMMENT_CHARS],
        "source": source,
        "at": _now(),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _lock:
        with PATH.open("a", encoding="utf-8") as handle:
            handle.write(line)
    return entry


def _read_all() -> list[dict]:
    """读取全部记录;坏行跳过,不让单行损坏拖垮报告。"""
    if not PATH.exists():
        return []
    entries: list[dict] = []
    try:
        with PATH.open(encoding="utf-8") as handle:
            for raw in handle:
                text = raw.strip()
                if not text:
                    continue
                try:
                    entry = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if (isinstance(entry, dict) and entry.get("uid")
                        and entry.get("pointId") and entry.get("score")):
                    entries.append(entry)
    except OSError:
        return []
    return entries


def for_user(uid: str) -> list[dict]:
    """该账号的全部诊断记录,按写入顺序(时间正序)。"""
    return [entry for entry in _read_all() if entry.get("uid") == uid]


def latest(uid: str) -> dict[str, dict]:
    """每个知识点只保留最后一次诊断。"""
    result: dict[str, dict] = {}
    for entry in for_user(uid):
        result[str(entry["pointId"])] = entry
    return result


def weak_report(uid: str, graph: KnowledgeGraph | None = None) -> dict:
    """薄弱点报告:掌握度低于阈值,按分数升序、核心度降序排列。"""
    graph = graph or get_graph()
    latest_map = latest(uid)
    weak: list[dict] = []
    for point_id, entry in latest_map.items():
        score = entry.get("score")
        if not isinstance(score, int) or score >= WEAK_THRESHOLD:
            continue
        point = graph.points.get(point_id)
        weak.append({
            "pointId": point_id,
            "name": point.name if point else point_id,
            "chapter": point.chapter if point else "",
            "difficulty": point.difficulty if point else 0,
            "descendantCount": graph.descendant_count(point_id) if point else 0,
            "score": score,
            "comment": entry.get("comment", ""),
            "source": entry.get("source", ""),
            "updatedAt": entry.get("at", ""),
        })
    weak.sort(key=lambda item: (item["score"], -item["descendantCount"], item["pointId"]))
    return {
        "weak": weak,
        "diagnosed": len(latest_map),
        "threshold": WEAK_THRESHOLD,
    }


def delete_user(uid: str) -> int:
    """删除该账号全部诊断记录,返回删除条数。"""
    entries = _read_all()
    kept = [entry for entry in entries if entry.get("uid") != uid]
    removed = len(entries) - len(kept)
    if not removed:
        return 0
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(PATH.suffix + ".tmp")
    with _lock:
        with tmp.open("w", encoding="utf-8") as handle:
            for entry in kept:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        tmp.replace(PATH)
    return removed


async def _llm_score(point: KnowledgePoint, answer: str) -> tuple[int, str]:
    """让模型按助教口径给掌握度打分;任何不可用都抛 DiagnosisUnavailable。"""
    system = (
        "你是高等数学助教,负责判断学生对某个知识点的掌握程度。"
        "只输出一个 JSON 对象,不要解释、不要 Markdown 代码块之外的内容:\n"
        '{"score": 1-5 的整数, "comment": "不超过 60 字的中文评语"}\n'
        "评分标准:1=概念不清;2=能复述但不会用;3=能完成常规题;"
        "4=能处理变形题;5=能讲清原理并迁移。"
    )
    user = (
        f"知识点:{point.name}(难度 {point.difficulty}/5)\n"
        f"前置知识:{'、'.join(point.prerequisites) or '无'}\n"
        f"学生回答:\n{answer[:MAX_ANSWER_CHARS]}"
    )
    parts: list[str] = []
    async for delta in rag.llm.stream_chat(system, user, role="main", thinking=False):
        parts.append(delta)
        if sum(len(part) for part in parts) >= 600:
            break
    try:
        return parse_result("".join(parts))
    except DiagnosisError as exc:
        raise DiagnosisUnavailable(f"诊断输出无法解析: {exc}") from None


def _point_or_404(point_id: str) -> KnowledgePoint:
    point = get_graph().points.get(point_id)
    if point is None:
        raise HTTPException(404, "unknown point")
    return point


async def diagnose(request: Request) -> JSONResponse:
    """POST /api/diagnosis

    body: {"pointId": "...", "answer": "..."} 或 {"pointId": "...", "selfRating": 3}
    有 answer 走模型评分,否则用自评;结果入库并返回。
    """
    rec = auth.require_auth(request)
    uid = str(rec.get("uid") or "")
    body = await http_utils.read_json_object(request, max_bytes=MAX_BODY_BYTES)

    point_id = body.get("pointId")
    if not isinstance(point_id, str) or not point_id.strip():
        raise HTTPException(400, "pointId required")
    point = _point_or_404(point_id.strip())

    answer = body.get("answer")
    answer = answer.strip() if isinstance(answer, str) else ""
    rating = body.get("selfRating")

    if answer:
        try:
            score, comment = await _llm_score(point, answer)
        except DiagnosisUnavailable as exc:
            raise HTTPException(503, str(exc)) from None
        except Exception as exc:  # noqa: BLE001 模型侧错误统一按服务不可用处理
            print(f"[diagnosis] 模型评分失败: {exc}")
            raise HTTPException(503, "diagnosis unavailable") from None
        source = "llm"
    elif rating is not None:
        try:
            score = int(rating)
        except (TypeError, ValueError):
            raise HTTPException(400, "invalid selfRating") from None
        if not 1 <= score <= 5:
            raise HTTPException(400, "invalid selfRating")
        comment = "学生自评"
        source = "self"
    else:
        raise HTTPException(400, "answer or selfRating required")

    entry = record(uid, point.id, score, comment, source=source)
    return JSONResponse({"ok": True, **entry})


async def weak_points(request: Request) -> JSONResponse:
    """GET /api/diagnosis/report:当前账号的薄弱点报告。"""
    rec = auth.require_auth(request)
    return JSONResponse(weak_report(str(rec.get("uid") or "")))
