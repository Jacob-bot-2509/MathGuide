"""
语音转写:浏览器录音 → 后端 ASR(不依赖 Web Speech / Google 语音服务)。

为什么需要这一层:
- 国产浏览器(红米/荣耀自带浏览器)常没有 `SpeechRecognition`;
- Android Chrome 的 Web Speech 依赖 Google 语音服务,校园网/国内网络可能不可达;
- Web Speech 还要求 HTTPS 安全上下文。

优先级:
    MG_ASR_PROVIDER=auto(默认)  智谱 glm-asr-2512 → Qwen Omni 兜底
    MG_ASR_PROVIDER=zhipu       只用智谱
    MG_ASR_PROVIDER=qwen        Qwen Omni 优先 → 智谱兜底

智谱接口:POST {MG_ASR_BASE_URL}/audio/transcriptions(multipart, WAV/MP3, ≤30s/25MB)
Qwen 接口:POST {MG_ALIYUN_BASE_URL}/chat/completions(input_audio, qwen3.8-omni-flash)

前端已把录音重采样为 16kHz 单声道 WAV 并限制 30 秒;这里是第二道大小/格式校验。
"""
from __future__ import annotations

import base64
import binascii
import os

import httpx
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

import quota
from auth import require_auth
from http_utils import read_json_object
from log import get_logger
from rate_limit import SlidingWindowLimiter

log = get_logger(__name__)

MAX_AUDIO_BYTES = 1_600_000  # ≈30s 16kHz mono 16-bit WAV;base64 后仍低于 2MB body 上限
MAX_BODY_BYTES = 2 * 1024 * 1024
ALLOWED_FORMATS = {"wav", "mp3"}
TIMEOUT = httpx.Timeout(connect=5.0, read=45.0, write=20.0, pool=5.0)
_limiter = SlidingWindowLimiter(20, 60)  # 每用户每分钟最多 20 次转写


def _zhipu_cfg() -> dict[str, str]:
    return {
        "base": (os.getenv("MG_ASR_BASE_URL", "")
                 or os.getenv("MG_ZHIPU_BASE_URL", "")
                 or "https://open.bigmodel.cn/api/paas/v4").rstrip("/"),
        "key": os.getenv("MG_ASR_API_KEY", "") or os.getenv("MG_ZHIPU_API_KEY", ""),
        "model": os.getenv("MG_ASR_MODEL", "") or "glm-asr-2512",
    }


def _qwen_cfg() -> dict[str, str]:
    return {
        "base": (os.getenv("MG_ASR_QWEN_BASE_URL", "")
                 or os.getenv("MG_ALIYUN_BASE_URL", "")).rstrip("/"),
        "key": os.getenv("MG_ASR_QWEN_API_KEY", "") or os.getenv("MG_ALIYUN_API_KEY", ""),
        "model": (os.getenv("MG_ASR_QWEN_MODEL", "")
                  or os.getenv("MG_VISION_MODEL", "")
                  or "qwen3.8-omni-flash"),
    }


def _providers() -> list[tuple[str, dict[str, str]]]:
    preferred = os.getenv("MG_ASR_PROVIDER", "auto").strip().lower()
    zhipu, qwen = _zhipu_cfg(), _qwen_cfg()
    providers: list[tuple[str, dict[str, str]]] = []
    if preferred == "zhipu":
        order = [("zhipu", zhipu)]
    elif preferred == "qwen":
        order = [("qwen", qwen), ("zhipu", zhipu)]
    else:
        # 当前实测 open.bigmodel.cn 可达;DashScope 在本机网络不可达,先走智谱。
        order = [("zhipu", zhipu), ("qwen", qwen)]
    for name, cfg in order:
        if cfg["base"] and cfg["key"] and cfg["model"]:
            providers.append((name, cfg))
    return providers


def _prompt(language: str) -> str:
    if language.lower().startswith("en"):
        return "Transcribe the speech verbatim. Output only the transcript, no explanation."
    return "请逐字转写这段音频,只输出转写文本,不要解释、不要补充。"


def _decode_audio(body: dict) -> tuple[bytes, str]:
    raw = body.get("audio")
    if not isinstance(raw, str) or not raw.strip():
        raise HTTPException(400, "audio required")
    if raw.startswith("data:"):
        raw = raw.partition(",")[2]
    try:
        data = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "invalid audio") from None
    if not data:
        raise HTTPException(400, "audio required")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large")
    fmt = str(body.get("format") or "wav").strip().lower().lstrip(".")
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(400, "unsupported audio format")
    return data, fmt


async def _zhipu_transcribe(cfg: dict[str, str], data: bytes, fmt: str,
                            prompt: str) -> str:
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
        res = await client.post(
            f"{cfg['base']}/audio/transcriptions",
            headers={"Authorization": f"Bearer {cfg['key']}"},
            data={"model": cfg["model"], "stream": "false", "prompt": prompt},
            files={"file": (f"speech.{fmt}", data, f"audio/{fmt}")},
        )
        res.raise_for_status()
        body = res.json()
    return str(body.get("text") or "").strip()


async def _qwen_transcribe(cfg: dict[str, str], data: bytes, fmt: str,
                           prompt: str) -> str:
    encoded = base64.b64encode(data).decode("ascii")
    audio = f"data:audio/{fmt};base64,{encoded}"
    payload = {
        "model": cfg["model"],
        "messages": [{
            "role": "user",
            "content": [
                {"type": "input_audio", "input_audio": {"data": audio, "format": fmt}},
                {"type": "text", "text": prompt},
            ],
        }],
        "stream": False,
        "reasoning_effort": "none",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT, trust_env=False) as client:
        res = await client.post(
            f"{cfg['base']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['key']}"},
            json=payload,
        )
        res.raise_for_status()
        body = res.json()
    choices = body.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content") or ""
    if isinstance(content, list):
        content = "".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        )
    return str(content).strip()


async def _transcribe(data: bytes, fmt: str, language: str) -> tuple[str, str, str]:
    prompt = _prompt(language)
    providers = _providers()
    if not providers:
        raise HTTPException(503, "speech recognition not configured")
    last_error = ""
    for name, cfg in providers:
        try:
            if name == "zhipu":
                text = await _zhipu_transcribe(cfg, data, fmt, prompt)
            else:
                text = await _qwen_transcribe(cfg, data, fmt, prompt)
            return text, name, cfg["model"]
        except Exception as exc:  # noqa: BLE001 - 换下一个提供方
            last_error = f"{name}: {type(exc).__name__}"
            log.warning(f"[speech-asr] {name} 转写失败: {type(exc).__name__}")
    log.warning(f"[speech-asr] 所有提供方均失败({last_error})")
    raise HTTPException(502, "speech recognition unavailable")


async def transcribe(request: Request) -> JSONResponse:
    """POST /api/speech/transcribe {audio: base64, format: wav|mp3, language?: zh|en}"""
    rec = require_auth(request)
    uid = str(rec.get("uid") or rec.get("phone") or "")
    if uid and not _limiter.allow(uid):
        raise HTTPException(429, "rate limited")
    quota.check(uid)

    body = await read_json_object(request, max_bytes=MAX_BODY_BYTES)
    data, fmt = _decode_audio(body)
    language = str(body.get("language") or "")
    text, provider, model = await _transcribe(data, fmt, language)
    return JSONResponse({"text": text, "provider": provider, "model": model})
