"""
本地配置加载:backend/.env.local(已被 .gitignore 排除,key 永不入库)。

用法:复制 .env.local.example → .env.local,填入真实 API Key。
main.py 启动时最先调用 load_env(),之后各模块经 os.getenv 读取。
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

ENV_FILE = Path(__file__).resolve().parent / ".env.local"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------- 部署安全 ----------

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def demo_mode() -> bool:
    """演示通道开关:默认开启(仅限本机);显式设 0/false/off/no 关闭。"""
    return os.getenv("MG_DEMO_MODE", "1").strip().lower() not in ("0", "false", "off", "no")


def cors_origins() -> list[str]:
    """允许跨域的前端来源;默认只放行本机 vite。"""
    raw = os.getenv(
        "MG_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    )
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def workspace_from_host(host: str | None) -> str:
    """按子域判定工作区:learn.* / research.* → 固定工作区。

    返回空字符串表示当前主机没有区分子域(本机开发、单域部署),
    由调用方退回请求体里的 workspace 字段。子域一旦命中,服务端
    以 Host 为准,客户端无法通过改请求体跨区。
    """
    name = (host or "").split(":", 1)[0].strip().lower()
    if name.startswith("research."):
        return "research"
    if name.startswith("learn."):
        return "learn"
    return ""


def invite_codes() -> set[str]:
    """测评邀请码;关闭演示模式后,只有持有效邀请码的手机号可注册。"""
    raw = os.getenv("MG_INVITE_CODES", "")
    return {code.strip() for code in raw.split(",") if code.strip()}


def _argv_host(argv: list[str] | None = None) -> str:
    """从 uvicorn 命令行取绑定地址:--host x / --host=x。"""
    args = sys.argv[1:] if argv is None else argv
    for index, arg in enumerate(args):
        if arg == "--host" and index + 1 < len(args):
            return args[index + 1].strip()
        if arg.startswith("--host="):
            return arg.split("=", 1)[1].strip()
    return ""


def bound_host(argv: list[str] | None = None) -> str:
    """当前进程的绑定地址;取不到时按 uvicorn 默认 127.0.0.1 处理。"""
    return (
        os.getenv("UVICORN_HOST")
        or _argv_host(argv)
        or os.getenv("MG_HOST")
        or "127.0.0.1"
    ).strip()


def _is_loopback_origin(origin: str) -> bool:
    parsed = urlsplit(origin)
    return bool(parsed.hostname) and parsed.hostname in LOOPBACK_HOSTS


def assert_safe_demo_mode(argv: list[str] | None = None) -> None:
    """演示模式只允许本机。公网绑定/公网 CORS 来源直接拒绝启动。

    这一层挡的是最常见的部署失误:直接 `uvicorn main:app --host 0.0.0.0`
    把固定验证码 123456 和开放注册暴露到公网。反向代理场景无法仅靠绑定
    地址判断,部署文档仍要求显式设置 MG_DEMO_MODE=0。
    """
    if not demo_mode():
        return
    host = bound_host(argv)
    if host not in LOOPBACK_HOSTS:
        raise RuntimeError(
            f"MG_DEMO_MODE=1 但绑定地址是 {host!r};演示模式只允许本机。"
            "公网部署请设置 MG_DEMO_MODE=0 后重启。"
        )
    origins = cors_origins()
    if "*" in origins:
        raise RuntimeError(
            "MG_DEMO_MODE=1 时 MG_CORS_ORIGINS 不能为 *;请改为具体的前端来源。"
        )
    public_origins = [origin for origin in origins if not _is_loopback_origin(origin)]
    if public_origins:
        raise RuntimeError(
            "MG_DEMO_MODE=1 时 CORS 只能放行本机来源;发现:"
            + ", ".join(public_origins)
            + "。公网部署请设置 MG_DEMO_MODE=0。"
        )
    print("[config] 演示模式开启:仅限本机访问;公网部署必须设置 MG_DEMO_MODE=0")
