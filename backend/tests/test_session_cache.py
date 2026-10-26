"""session_cache.py:跨用户隔离、LRU 淘汰与登出清理。"""
from __future__ import annotations

import session_cache as sc


def test_textbook_is_isolated_by_uid():
    sc.cache_textbook("user-a", 1, "A 的教材" * 30)
    sc.cache_textbook("user-b", 1, "B 的教材" * 30)

    assert sc.get_textbook("user-a", 1).startswith("A 的教材")
    assert sc.get_textbook("user-b", 1).startswith("B 的教材")
    assert sc.get_textbook("user-c", 1) == ""


def test_summary_is_isolated_by_uid():
    sc.set_summary("a", 1, "A 的摘要")
    sc.set_summary("b", 1, "B 的摘要")
    assert sc.get_summary("a", 1) == "A 的摘要"
    assert sc.get_summary("b", 1) == "B 的摘要"
    assert sc.get_summary("c", 1) == ""


def test_invalid_session_ids_are_ignored():
    for sid in (None, 0, -1, True, "1", 1.5):
        sc.cache_textbook("u", sid, "x" * 100)
        assert sc.get_textbook("u", sid) == ""
        assert sc.bump_tick("u", sid) == 0


def test_empty_uid_is_never_shared():
    """拿不到 uid 时宁可不缓存,也不能退化成所有人共用的空键桶。"""
    sc.cache_textbook("", 1, "x" * 100)
    sc.cache_textbook(None, 1, "y" * 100)
    assert sc.get_textbook("", 1) == ""
    assert sc.get_textbook(None, 1) == ""
    assert sc.get_summary("", 1) == ""
    assert sc.bump_tick("", 1) == 0


def test_textbook_lru_eviction():
    for i in range(sc.TEXTBOOK_MAX + 1):
        sc.cache_textbook("u", i + 1, f"教材{i}" * 30)
    assert sc.get_textbook("u", 1) == ""          # 最旧被淘汰
    assert sc.get_textbook("u", sc.TEXTBOOK_MAX + 1).startswith(f"教材{sc.TEXTBOOK_MAX}")


def test_get_refreshes_lru_order():
    for i in range(sc.TEXTBOOK_MAX):
        sc.cache_textbook("u", i + 1, f"教材{i}" * 30)
    # 访问最旧的,使其变成最新;再插入一条应淘汰第二旧的
    assert sc.get_textbook("u", 1)
    sc.cache_textbook("u", 999, "新教材" * 30)
    assert sc.get_textbook("u", 1)              # 仍在
    assert sc.get_textbook("u", 2) == ""        # 被淘汰


def test_clear_user_only_touches_that_user():
    sc.cache_textbook("a", 1, "x" * 100)
    sc.set_summary("a", 1, "s")
    sc.bump_tick("a", 1)
    sc.cache_textbook("b", 1, "y" * 100)

    sc.clear_user("a")

    assert sc.get_textbook("a", 1) == ""
    assert sc.get_summary("a", 1) == ""
    assert sc.bump_tick("a", 1) == 1  # 计数已清零
    assert sc.get_textbook("b", 1).startswith("y")


def test_tick_is_per_session():
    assert sc.bump_tick("u", 1) == 1
    assert sc.bump_tick("u", 1) == 2
    assert sc.bump_tick("u", 2) == 1
