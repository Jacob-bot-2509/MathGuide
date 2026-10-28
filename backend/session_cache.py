"""会话级临时缓存:教材正文、滚动摘要与摘要节拍。

键必须是 (uid, workspace, session_id)。session_id 由客户端提供,且前端每个
浏览器的 nextSessionId() 都从 1 开始 —— 只按 session_id 存会让不同用户撞号,
把对方的教材/摘要拼进本用户的模型上下文(跨用户泄漏)。workspace 再隔一层:
学习辅助与科学研究的 sessionId 各自从 1 开始,同一用户也会撞号。

进程内单实例;服务重启即失效,前端已有「缓存失效按通用知识作答」的降级路径。
"""
from __future__ import annotations

from collections import OrderedDict

TEXTBOOK_CAP = 30000  # 与前端 FILE_TEXT_MAX / chat.PROMPT_MAX 同一量级
TEXTBOOK_MAX = 16
SUMMARY_MAX = 64
TICK_MAX = 4096
VALID_SESSION_MIN = 1
VALID_WORKSPACES = ("learn", "research")
DEFAULT_WORKSPACE = "learn"

Key = tuple[str, str, int]


def valid_workspace(value: object) -> str:
    """工作区名 → 白名单内的值;未知/缺失一律按 learn(旧客户端兼容)。"""
    return value if isinstance(value, str) and value in VALID_WORKSPACES else DEFAULT_WORKSPACE

_textbooks: OrderedDict[Key, str] = OrderedDict()
_summaries: OrderedDict[Key, str] = OrderedDict()
_ticks: OrderedDict[Key, int] = OrderedDict()


def valid_session_id(value: object) -> int | None:
    """客户端 sessionId → 合法正整数;bool 是 int 子类,必须显式排除。"""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if value >= VALID_SESSION_MIN else None


def _owner(uid: object) -> str:
    return str(uid or "")


def _key(uid: object, session_id: object, workspace: object = DEFAULT_WORKSPACE) -> Key | None:
    """(uid, workspace, session_id) → 缓存键;任一侧无效时返回 None(调用方跳过缓存)。

    uid 为空不能退化成共享键 "":否则所有拿不到 uid 的调用会挤进同一个桶,
    重新出现「B 读到 A 的教材/摘要」。宁可这次不缓存,也不共用桶。
    """
    owner = _owner(uid)
    sid = valid_session_id(session_id)
    if not owner or sid is None:
        return None
    return (owner, valid_workspace(workspace), sid)


def cache_textbook(uid: object, session_id: object, text: str,
                   workspace: object = DEFAULT_WORKSPACE) -> None:
    """缓存教材正文;同一个 (uid, workspace, session) 再次上传时覆盖(最近一次为准)。"""
    key = _key(uid, session_id, workspace)
    if key is None or len(text) < 80:
        return
    _textbooks[key] = text[:TEXTBOOK_CAP]
    _textbooks.move_to_end(key)
    while len(_textbooks) > TEXTBOOK_MAX:
        _textbooks.popitem(last=False)


def get_textbook(uid: object, session_id: object,
                 workspace: object = DEFAULT_WORKSPACE) -> str:
    key = _key(uid, session_id, workspace)
    if key is None:
        return ""
    text = _textbooks.get(key)
    if text is None:
        return ""
    _textbooks.move_to_end(key)
    return text


def get_summary(uid: object, session_id: object,
                workspace: object = DEFAULT_WORKSPACE) -> str:
    key = _key(uid, session_id, workspace)
    if key is None:
        return ""
    text = _summaries.get(key)
    if text is None:
        return ""
    _summaries.move_to_end(key)
    return text


def set_summary(uid: object, session_id: object, text: str,
                workspace: object = DEFAULT_WORKSPACE) -> None:
    key = _key(uid, session_id, workspace)
    if key is None or not text:
        return
    _summaries[key] = text
    _summaries.move_to_end(key)
    while len(_summaries) > SUMMARY_MAX:
        _summaries.popitem(last=False)


def bump_tick(uid: object, session_id: object,
              workspace: object = DEFAULT_WORKSPACE) -> int:
    """会话摘要节拍 +1;用于「每 8 轮压缩一次」。"""
    key = _key(uid, session_id, workspace)
    if key is None:
        return 0
    tick = _ticks.get(key, 0) + 1
    _ticks[key] = tick
    _ticks.move_to_end(key)
    while len(_ticks) > TICK_MAX:
        _ticks.popitem(last=False)
    return tick


def clear_user(uid: object) -> None:
    """清除某用户的全部会话缓存(登出时调用)。"""
    owner = _owner(uid)
    if not owner:
        return
    for cache in (_textbooks, _summaries):
        for key in [k for k in cache if k[0] == owner]:
            del cache[key]
    for key in [k for k in _ticks if k[0] == owner]:
        del _ticks[key]


def reset() -> None:
    """清空全部缓存(测试用)。"""
    _textbooks.clear()
    _summaries.clear()
    _ticks.clear()
