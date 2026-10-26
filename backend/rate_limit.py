"""进程内滑动窗口限流(单进程 asyncio,无需锁)。

用于聊天与认证接口:同一 key(用户 uid / 客户端 IP)在 window 秒内最多
max_hits 次。超限由调用方转成 HTTP 429。

字典按需清理:游客登录会不断产生新 key,不清理会让内存无界增长。
清理在字典超过 max_keys 时触发;若仍超限,按插入顺序淘汰最旧的 key
(限流是尽力而为的保护,内存有界优先)。
"""
from __future__ import annotations

import time
from collections import deque


class SlidingWindowLimiter:
    def __init__(self, max_hits: int, window: float, max_keys: int = 4096):
        if max_hits < 1:
            raise ValueError("max_hits must be >= 1")
        if window <= 0:
            raise ValueError("window must be > 0")
        if max_keys < 1:
            raise ValueError("max_keys must be >= 1")
        self.max_hits = max_hits
        self.window = window
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str, now: float | None = None) -> bool:
        """记录一次访问。未超限返回 True;超限返回 False(超限请求不计数)。"""
        t = time.monotonic() if now is None else now
        self._sweep_if_needed(t, keep=key)

        hits = self._hits.get(key)
        if hits is None:
            hits = self._hits[key] = deque()

        cutoff = t - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.max_hits:
            return False

        hits.append(t)
        # 新增 key 后可能越界;再清理一次,保证字典大小有上界(当前 key 绝不淘汰)
        self._sweep_if_needed(t, keep=key)
        return True

    def reset(self, key: str | None = None) -> None:
        """清空某个 key(测试用)或全部记录。"""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)

    def _sweep_if_needed(self, now: float, keep: str | None = None) -> None:
        """超容时清理:先删窗口内已无命中的 key,再按「最后活跃时间」淘汰最久未动的。

        `keep` 是本次请求的 key:淘汰必须绕开它,否则批量造 key 的调用方
        可以把某个活跃 key(含自己刚记的那条)挤掉,计数归零后限流形同虚设。
        """
        if len(self._hits) <= self.max_keys:
            return
        cutoff = now - self.window
        stale = [k for k, hits in self._hits.items()
                 if k != keep and (not hits or hits[-1] <= cutoff)]
        for key in stale:
            del self._hits[key]
        while len(self._hits) > self.max_keys:
            candidates = [k for k in self._hits if k != keep]
            if not candidates:
                break  # 只剩当前 key:宁可不淘汰,也不自毁计数
            victim = min(
                candidates,
                key=lambda k: self._hits[k][-1] if self._hits[k] else float("-inf"),
            )
            del self._hits[victim]
