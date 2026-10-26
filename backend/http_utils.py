"""HTTP 请求体解析:统一大小上限与 400 语义。

Starlette 的 request.json() 会先把整个 body 读进内存,业务层再截断就晚了;
非法 JSON / 非对象 body 还会变成 500。这里按块累计、超限返回 413,
然后只接受 JSON 对象,其余一律 400。
"""
from __future__ import annotations

import json

from starlette.exceptions import HTTPException
from starlette.requests import Request

# 2 MiB:聊天上限 3.2 万字(UTF-8 最多约 128KB)+ 16 条历史 + 教材,
# 以及 PDF 导出的 3.2 万字正文,余量充足。
MAX_BODY_BYTES = 2 * 1024 * 1024


def _sanitize_json(value):
    """把 JSON 里非法的孤立代理项(如 "\\ud800")替换为 U+FFFD。

    json.loads 能解析这类转义,但后续 password.encode("utf-8") 会抛
    UnicodeEncodeError,把一次登录变成 500;统一在入口处清洗。
    """
    if isinstance(value, str):
        try:
            value.encode("utf-8")
            return value
        except UnicodeEncodeError:
            # surrogatepass 先把孤立代理项编成字节,再按 UTF-8 replace 解码成 U+FFFD
            return value.encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    if isinstance(value, list):
        return [_sanitize_json(item) for item in value]
    if isinstance(value, dict):
        return {
            _sanitize_json(k) if isinstance(k, str) else k: _sanitize_json(v)
            for k, v in value.items()
        }
    return value


async def read_json_object(request: Request, max_bytes: int | None = None) -> dict:
    """读取并解析 JSON 对象;超过上限 413,非法 JSON / 非对象 400。"""
    limit = MAX_BODY_BYTES if max_bytes is None else max_bytes

    content_length = request.headers.get("content-length", "")
    # 先看位数再转 int:超过 4300 位的数字串会让 int() 抛 ValueError(Python 3.11+
    # 的整数转换位数上限),那会把本该 413 的请求变成 500
    if content_length.isdigit() and (len(content_length) > 20 or int(content_length) > limit):
        raise HTTPException(413, "payload too large")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise HTTPException(413, "payload too large")
        chunks.append(chunk)

    try:
        body = json.loads(b"".join(chunks))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(400, "invalid json") from None

    if not isinstance(body, dict):
        raise HTTPException(400, "invalid json")
    return _sanitize_json(body)
