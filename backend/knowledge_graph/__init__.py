"""数学知识点知识图谱。

CSV 是唯一真源:每行一个知识点,`prerequisites` 用分号分隔前置知识点 id。
加载时完成结构校验(重复 id、缺失前置、自依赖、难度范围、无环),
并预先计算直接后继与传递后继数量(核心度),供诊断与路径推荐使用。

CSV 列(表头必须齐全,顺序不限):
    id,name,chapter,difficulty,prerequisites
"""
from __future__ import annotations

import csv
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CSV = Path(__file__).resolve().parent / "data" / "knowledge_points.csv"
DEFAULT_NOTES = Path(__file__).resolve().parent / "data" / "point_notes.json"
REQUIRED_COLUMNS = ("id", "name", "chapter", "difficulty", "prerequisites")
SUMMARY_MAX = 800
KEY_POINT_MAX = 200


class KnowledgeGraphError(ValueError):
    """CSV 结构或依赖关系不合法。"""


@dataclass(frozen=True)
class KnowledgePoint:
    id: str
    name: str
    chapter: str
    difficulty: int
    prerequisites: tuple[str, ...]
    summary: str = ""
    key_points: tuple[str, ...] = ()


class KnowledgeGraph:
    """只读图结构。构造前由 load_graph 完成合法性校验。"""

    def __init__(self, points: dict[str, KnowledgePoint]):
        self.points = points
        dependents: dict[str, list[str]] = {pid: [] for pid in points}
        for point in points.values():
            for prereq in point.prerequisites:
                dependents[prereq].append(point.id)
        self._dependents = {pid: tuple(ids) for pid, ids in dependents.items()}
        self._descendant_counts = {
            pid: self._count_descendants(pid) for pid in points
        }

    def direct_dependents(self, point_id: str) -> tuple[str, ...]:
        """直接依赖该知识点的后续知识点(核心度的一阶口径)。"""
        return self._dependents[point_id]

    def descendant_count(self, point_id: str) -> int:
        """传递后继数量:掌握该点后能解锁的知识点总数。"""
        return self._descendant_counts[point_id]

    def topological_order(self) -> list[str]:
        """拓扑序;存在环时抛 KnowledgeGraphError。同层按 CSV 顺序稳定输出。"""
        indegree = {
            pid: len(point.prerequisites) for pid, point in self.points.items()
        }
        ready = deque(pid for pid in self.points if indegree[pid] == 0)
        order: list[str] = []
        while ready:
            pid = ready.popleft()
            order.append(pid)
            for dependent in self._dependents[pid]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        if len(order) != len(self.points):
            cycle = [pid for pid, degree in indegree.items() if degree > 0]
            raise KnowledgeGraphError(
                f"知识点依赖存在循环: {'、'.join(cycle)}"
            )
        return order

    def _count_descendants(self, point_id: str) -> int:
        seen: set[str] = set()
        stack = list(self._dependents[point_id])
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            stack.extend(self._dependents[current])
        return len(seen)


def _split_prerequisites(raw: str) -> tuple[str, ...]:
    """分号分隔(兼容中文分号);空单元格表示无前置。"""
    parts = raw.replace("；", ";").split(";")
    return tuple(part.strip() for part in parts if part.strip())


def _load_notes(path: str | Path | None) -> dict[str, dict]:
    """读取知识点摘要 JSON;缺失文件视为无内容,结构错误直接拒绝。"""
    if path is None:
        return {}
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise KnowledgeGraphError(f"{path.name}: JSON 无效 ({exc.msg})") from None
    if not isinstance(raw, dict):
        raise KnowledgeGraphError(f"{path.name}: 笔记根节点必须是对象")
    notes: dict[str, dict] = {}
    for point_id, value in raw.items():
        if not isinstance(value, dict):
            raise KnowledgeGraphError(f"{path.name}: 笔记 {point_id} 必须是对象")
        summary = value.get("summary")
        key_points = value.get("keyPoints")
        if not isinstance(summary, str):
            raise KnowledgeGraphError(f"{path.name}: 笔记 {point_id} 的 summary 必须是字符串")
        if not isinstance(key_points, list) or not all(
                isinstance(item, str) for item in key_points):
            raise KnowledgeGraphError(
                f"{path.name}: 笔记 {point_id} 的 keyPoints 必须是字符串数组")
        notes[str(point_id)] = {
            "summary": summary.strip()[:SUMMARY_MAX],
            "key_points": tuple(
                item.strip()[:KEY_POINT_MAX] for item in key_points if item.strip()),
        }
    return notes


def load_graph(path: str | Path = DEFAULT_CSV,
               notes_path: str | Path | None = None) -> KnowledgeGraph:
    """读取并校验知识点 CSV 与可选摘要 JSON,返回只读图。

    默认摘要只跟随默认 CSV 加载;测试/临时 CSV 不会误读项目笔记。
    """
    path = Path(path)
    if notes_path is None and path.resolve() == DEFAULT_CSV.resolve():
        notes_path = DEFAULT_NOTES
    notes = _load_notes(notes_path)
    points: dict[str, KnowledgePoint] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [
            column for column in REQUIRED_COLUMNS
            if column not in (reader.fieldnames or [])
        ]
        if missing:
            raise KnowledgeGraphError(
                f"{path.name}: 缺少列: {', '.join(missing)}"
            )

        for row in reader:
            line = reader.line_num
            point_id = (row.get("id") or "").strip()
            if not point_id:
                raise KnowledgeGraphError(f"{path.name} 第{line}行: 缺少 id")
            if point_id in points:
                raise KnowledgeGraphError(f"知识点 id 重复: {point_id}")

            raw_difficulty = (row.get("difficulty") or "").strip()
            try:
                difficulty = int(raw_difficulty)
            except ValueError:
                raise KnowledgeGraphError(
                    f"{path.name} 第{line}行: 难度必须是 1~5 的整数,"
                    f"实际为 {raw_difficulty!r}"
                ) from None
            if not 1 <= difficulty <= 5:
                raise KnowledgeGraphError(
                    f"{path.name} 第{line}行: 难度必须在 1~5 之间,"
                    f"实际为 {difficulty}"
                )

            prerequisites = _split_prerequisites(
                (row.get("prerequisites") or "").strip()
            )
            if point_id in prerequisites:
                raise KnowledgeGraphError(
                    f"知识点 {point_id} 不能依赖自身"
                )
            note = notes.get(point_id, {})
            points[point_id] = KnowledgePoint(
                id=point_id,
                name=(row.get("name") or "").strip(),
                chapter=(row.get("chapter") or "").strip(),
                difficulty=difficulty,
                prerequisites=prerequisites,
                summary=note.get("summary", ""),
                key_points=note.get("key_points", ()),
            )

    if not points:
        raise KnowledgeGraphError(f"{path.name}: 没有知识点")

    for note_id in notes:
        if note_id not in points:
            raise KnowledgeGraphError(
                f"{path.name}: 笔记引用了不存在的知识点: {note_id}")

    for point in points.values():
        for prereq in point.prerequisites:
            if prereq not in points:
                raise KnowledgeGraphError(
                    f"{point.id}: 前置知识点不存在: {prereq}"
                )

    graph = KnowledgeGraph(points)
    graph.topological_order()  # 构造即校验:DAG 之外的结构不允许流入上层
    return graph
