"""rate_limit.py:滑动窗口边界、过期清理与内存上限。"""
from __future__ import annotations

from rate_limit import SlidingWindowLimiter


def test_allow_and_limit():
    limiter = SlidingWindowLimiter(2, 60)
    assert limiter.allow("u", now=0) is True
    assert limiter.allow("u", now=1) is True
    assert limiter.allow("u", now=2) is False
    # 窗口滑过后恢复
    assert limiter.allow("u", now=61) is True


def test_keys_are_independent():
    limiter = SlidingWindowLimiter(1, 60)
    assert limiter.allow("a", now=0) is True
    assert limiter.allow("b", now=0) is True
    assert limiter.allow("a", now=1) is False


def test_stale_keys_are_swept_when_over_capacity():
    limiter = SlidingWindowLimiter(1, 10, max_keys=1)
    assert limiter.allow("old", now=0) is True
    assert limiter.allow("mid", now=0) is True
    # 新 key 让字典超容;过期 key 应被清掉而不是无限增长
    assert limiter.allow("new", now=100) is True
    assert len(limiter._hits) == 1
    assert "old" not in limiter._hits
    assert "mid" not in limiter._hits
    assert "new" in limiter._hits


def test_active_keys_are_bounded_even_without_stale_entries():
    limiter = SlidingWindowLimiter(5, 60, max_keys=2)
    for i in range(10):
        assert limiter.allow(f"k{i}", now=0) is True
    assert len(limiter._hits) <= 2


def test_sweep_never_evicts_the_current_key():
    limiter = SlidingWindowLimiter(5, 60, max_keys=1)
    assert limiter.allow("old", now=0) is True
    assert limiter.allow("current", now=0) is True
    assert "current" in limiter._hits
    assert "old" not in limiter._hits


def test_reset():
    limiter = SlidingWindowLimiter(1, 60)
    assert limiter.allow("u", now=0) is True
    limiter.reset("u")
    assert limiter.allow("u", now=1) is True
    limiter.reset()
    assert limiter._hits == {}


def test_rejects_invalid_config():
    for args in ((0, 60), (1, 0), (1, 60, 0)):
        try:
            SlidingWindowLimiter(*args)
        except ValueError:
            pass
        else:  # pragma: no cover
            raise AssertionError(f"expected ValueError for {args}")
