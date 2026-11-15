"""
本地配置加载:backend/.env.local(已被 .gitignore 排除,key 永不入库)。

用法:复制 .env.local.example → .env.local,填入真实 API Key。
main.py 启动时最先调用 load_env(),之后各模块经 os.getenv 读取。
"""
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

from log import get_logger

log = get_logger(__name__)

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


def daily_llm_limit() -> int:
    """每账号每天的模型请求上限;0 = 不限(默认)。

    测评期用它兜住"单个账号把额度刷穿"的风险:按 usage 表里当天的记录数计,
    超限直接 429。计数口径与 /api/stats、账号导出同一份数据,不额外维护计数器。
    """
    raw = os.getenv("MG_DAILY_LLM_CALLS", "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def detect_workers(argv: list[str] | None = None) -> int:
    """uvicorn/gunicorn 的 worker 数(拿不到按 1)。

    为什么专门做这个判断:限流器(`rate_limit`)、会话缓存(`session_cache`)、
    聊天检索缓存都是**进程内存**。多 worker 会让"每账号 6 次/分"变成 6×N 次、
    缓存各存一份互不可见。这里只负责报数,由 `assert_single_worker` 决定放不放行。
    """
    args = sys.argv[1:] if argv is None else argv
    for index, arg in enumerate(args):
        if arg == "--workers" and index + 1 < len(args):
            value = args[index + 1].strip()
        elif arg.startswith("--workers="):
            value = arg.split("=", 1)[1].strip()
        else:
            continue
        try:
            return max(1, int(value))
        except ValueError:
            return 1
    raw = os.getenv("WEB_CONCURRENCY", "").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def assert_single_worker(argv: list[str] | None = None) -> None:
    """多 worker 直接拒绝启动(演示模式只提示,方便本机反复起停)。

    为什么是硬拒绝而不是一句 WARNING:限流额度、会话缓存、检索缓存都是进程内存实现,
    N 个 worker 下"每账号 6 次/分"实际是 6×N 次,登出/吊销只在其中一个进程生效 ——
    这不是"慢一点",而是**额度与失效语义失真**,评测或公网环境下会直接变事故。
    日志里出现过警告不代表有人看见,所以默认改成启动即失败,把问题挡在部署窗口内。
    """
    workers = detect_workers(argv)
    if workers <= 1:
        return
    message = (
        f"检测到 {workers} 个 worker,但本服务不支持多进程:限流额度、会话缓存、"
        "检索缓存都是进程内存实现,多 worker 会让额度变成 N 倍且缓存各存一份。"
        "请去掉 --workers / WEB_CONCURRENCY,保持单进程"
        "(要提并发,优先加机器或前置队列,不要加 worker;见 deploy/README.md)。"
    )
    if demo_mode():
        log.warning(f"[config] {message}(演示模式仅提示,公网部署会直接拒绝启动)")
        return
    raise RuntimeError(message)


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
    log.info("[config] 演示模式开启:仅限本机访问;公网部署必须设置 MG_DEMO_MODE=0")
