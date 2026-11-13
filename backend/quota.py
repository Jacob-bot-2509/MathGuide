"""每日额度护栏:按账号限制"当天能发起多少次模型请求"(测评期成本上限)。

为什么放在 HTTP 入口、而不是模型客户端:

- 额度是**用户可感知**的配额(429 + 明确提示),应该在任何昂贵工作开始**之前**判定;
  放到客户端只能事后拦截 —— 钱已经花了;
- 计数口径复用 `usage` 表(与 /api/stats、账号导出同一份数据),
  不额外维护计数器,多 worker / 重启 / 手工改库都不会算错。

配置:`MG_DAILY_LLM_CALLS`(0 = 不限,默认)。
"""
from __future__ import annotations

from starlette.exceptions import HTTPException

import config
import usage


def check(uid: str) -> None:
    """超过当天额度抛 429;未配置额度(0)时直接返回。"""
    limit = config.daily_llm_limit()
    if limit <= 0 or not uid:
        return
    if usage.count_since(uid, usage.day_start()) >= limit:
        raise HTTPException(429, "daily quota reached")
