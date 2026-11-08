"""知识图谱分层布局(NetworkX)。

算法:最长路径分层 + 重心法排序,输出固定像素坐标。
- 分层:x(v) = max(x(前置) + 1),前置必须在左侧;
- 排序:同层节点按相邻层邻居的平均位置排序(重心法),减少交叉;
- 确定性:不使用随机数/spring 布局,同一份图输出完全相同,便于测试与缓存。

前端仍负责渲染与交互;坐标由后端给出,NetworkX 只做图计算。
"""
from __future__ import annotations

from collections import defaultdict

import networkx as nx

from knowledge_graph import KnowledgeGraph

NODE_GAP = 58
LEVEL_GAP = 230
MARGIN = 56
_SWEEPS = 4


def _build(graph: KnowledgeGraph) -> nx.DiGraph:
    g = nx.DiGraph()
    for point in graph.points.values():
        g.add_node(point.id)
    for point in graph.points.values():
        for prereq in point.prerequisites:
            g.add_edge(prereq, point.id)
    return g


def _levels(graph: KnowledgeGraph, g: nx.DiGraph) -> dict[str, int]:
    """最长路径分层;输入保证无环,损坏图按 0 层兜底。"""
    try:
        order = list(nx.topological_sort(g))
    except nx.NetworkXUnfeasible:
        return {point_id: 0 for point_id in graph.points}
    level = {point_id: 0 for point_id in order}
    for point_id in order:
        for dependent in g.successors(point_id):
            level[dependent] = max(level[dependent], level[point_id] + 1)
    return level


def _order_levels(graph: KnowledgeGraph, g: nx.DiGraph,
                  level: dict[str, int]) -> list[list[str]]:
    """重心法排序:上行看前置、下行看后继,多轮收敛;同分保持 CSV 顺序。"""
    buckets: list[list[str]] = [[] for _ in range(max(level.values(), default=0) + 1)]
    for point_id in graph.points:  # dict 保持 CSV 顺序
        buckets[level[point_id]].append(point_id)

    position = {
        node: index
        for bucket in buckets
        for index, node in enumerate(bucket)
    }
    for _ in range(_SWEEPS):
        for index in range(1, len(buckets)):
            buckets[index].sort(key=lambda node, idx=index: (
                _barycenter(g.predecessors(node), position, only_level=idx - 1),
                position[node],
            ))
            position.update({node: i for i, node in enumerate(buckets[index])})
        for index in range(len(buckets) - 2, -1, -1):
            buckets[index].sort(key=lambda node, idx=index: (
                _barycenter(g.successors(node), position, only_level=idx + 1),
                position[node],
            ))
            position.update({node: i for i, node in enumerate(buckets[index])})
    return buckets


def _barycenter(neighbors, position: dict[str, int], only_level: int) -> float:
    """邻居的平均纵向位置;没有相关邻居时排到本层末尾。"""
    values = [position[n] for n in neighbors if n in position]
    return sum(values) / len(values) if values else float("inf")


def layout_points(graph: KnowledgeGraph) -> dict[str, dict]:
    """返回 {知识点 id: {x, y, level}};坐标单位为像素。"""
    g = _build(graph)
    level = _levels(graph, g)
    buckets = _order_levels(graph, g, level)
    max_rows = max((len(bucket) for bucket in buckets), default=1)
    layout: dict[str, dict] = {}
    for level_index, bucket in enumerate(buckets):
        offset = (max_rows - len(bucket)) / 2
        for row, point_id in enumerate(bucket):
            layout[point_id] = {
                "x": MARGIN + level_index * LEVEL_GAP,
                "y": int(MARGIN + (offset + row) * NODE_GAP),
                "level": level_index,
            }
    return layout
