"""LLM 平台连通性 / 容灾自检(部署项 2.5)。

为什么必须在服务器上跑:
- 本机能通不代表目标机通:LLM 客户端是 `trust_env=False` 直连,出口 IP 白名单、
  机房 DNS、平台侧地域限流都会让「本机好好的」在线上变成 401/超时;
- **备胎是不是真的接管,只有把主用打坏才会暴露**。这件事等到线上出事才发现,
  就等于没有备胎 —— 所以 `--failover` 会临时把主用 key 改成无效值,再用真实的
  流式调用看它有没有切到异平台。整个过程只改本进程的环境变量,不动 .env.local。

用法(backend 目录下):
    python tools/check_llm.py                 # 四个角色各发一句话
    python tools/check_llm.py --role main     # 只测主力
    python tools/check_llm.py --failover      # 打坏主用,验证 backup 接管
    python tools/check_llm.py --json          # 机器可读(接监控/存档)

退出码:0 = 全部通过(未配置的角色记 SKIP);1 = 有失败项。

注意:deep/long 是思考型模型,首字可能十几秒;`--timeout` 默认 120s,别按 main 的
20s 去看门狗,否则会把「模型在想」误判成「链路断了」。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402  装载 .env.local(与 main.py 同一路径)
from rag import embed, llm  # noqa: E402

ROLES = ("main", "backup", "deep", "long")
SYSTEM = "你是连通性探针,只回两个字。"
USER = "回答两个字:在线"
MAX_TOKENS = 16
#: 平台名 → 该平台 API key 的环境变量名(`_providers()` 里就是这么读的)
PROVIDER_KEY_ENV = {
    "aliyun": "MG_ALIYUN_API_KEY",
    "zhipu": "MG_ZHIPU_API_KEY",
    "deepseek": "MG_DEEPSEEK_API_KEY",
}
RED, GREEN, YELLOW, GREY, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[90m", "\033[0m"


def provider_key_env(provider: str) -> str:
    """平台名 → key 的环境变量名;未知平台按 `MG_<PROVIDER>_API_KEY` 推断。"""
    return PROVIDER_KEY_ENV.get(provider.lower(), f"MG_{provider.upper()}_API_KEY")


def host_of(base: str) -> str:
    """base_url → 主机名。只打印主机:既能定位「打到了错的网关」,又不泄露 key。"""
    return urlsplit(base).netloc or base


def provider_of(spec: str) -> str:
    """角色配置串 "平台:模型" → 平台名。"""
    return spec.partition(":")[0].strip().lower() if ":" in spec else ""


def host_hint(exc: Exception) -> str:
    """按异常给「下一步查什么」:现场最需要区分的是 key 错、限流还是网络不通。"""
    text = f"{exc.__class__.__name__}: {exc}".lower()
    if "401" in text or "403" in text or "invalid" in text or "unauthorized" in text:
        return "key 或出口 IP 白名单:核对 MG_*_API_KEY 是否复制完整、是否需在平台加白"
    if "429" in text or "rate" in text or "quota" in text or "limit" in text:
        return "被限流/额度用尽:查平台控制台额度;必要时调小 MG_DAILY_LLM_CALLS"
    if "timeout" in text or "connect" in text or "resolve" in text or "ssl" in text:
        return "网络不通:LLM 是直连(trust_env=False),确认目标机出网与 DNS,别指望系统代理"
    return "看平台控制台与该角色配置(MG_ROLE_*),必要时把 key 换到备胎平台先保可用"


async def collect(agen, timeout: float) -> tuple[str, float | None, float]:
    """把流收成 (正文, 首字秒数, 总秒数);整体受 timeout 硬限,避免一条流拖死自检。"""
    started = time.monotonic()
    first: float | None = None
    chunks: list[str] = []

    async def drain() -> None:
        nonlocal first
        async for delta in agen:
            if first is None:
                first = time.monotonic() - started
            chunks.append(delta)

    await asyncio.wait_for(drain(), timeout)
    return "".join(chunks), first, time.monotonic() - started


async def probe_role(role: str, timeout: float) -> dict:
    """对单个角色发一句最短的话,回报模型/主机/首字/字数。"""
    spec = llm.resolve(role)
    spec_text = os.getenv(f"MG_ROLE_{role.upper()}", "")
    if spec is None:
        return {"role": role, "status": "skip",
                "detail": f"未配置(角色定义 {spec_text or '无'}:缺 base_url 或 key)"}
    base, _key, model = spec
    try:
        text, ttft, total = await collect(
            llm.stream_chat(SYSTEM, USER, role=role, fallback=False,
                            thinking=False, max_tokens=MAX_TOKENS),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 任何异常都要落成一条结论,不能中断整轮
        return {"role": role, "status": "fail", "model": model, "host": host_of(base),
                "detail": f"{exc.__class__.__name__}: {exc}", "hint": host_hint(exc)}
    if not text.strip():
        return {"role": role, "status": "fail", "model": model, "host": host_of(base),
                "detail": "模型在线但没出正文(可能只回了思考帧)",
                "hint": "提高 --timeout 再试;仍空则换模型"}
    return {"role": role, "status": "ok", "model": model, "host": host_of(base),
            "ttft": ttft, "total": total, "chars": len(text),
            "detail": f"{model} @ {host_of(base)} · 首字 {ttft:.2f}s / 总 {total:.2f}s · {len(text)} 字"}


async def probe_failover(timeout: float) -> dict:
    """打坏主用,验证 `stream_chat` 真的切到了异平台备胎。

    手法:临时把主用平台的 key 换成无效值 + 包一层 `_stream_once` 记录每次尝试,
    然后走**真实**的 `stream_chat(fallback=True)`。判据两条:
      1. 至少尝试了两次(第一次确实失败并进入容灾分支);
      2. 最后一次的模型/主机与第一次不同(落到的是异平台,不是同平台重试)。
    """
    if llm.resolve("main") is None or llm.resolve("backup") is None:
        return {"role": "failover", "status": "skip",
                "detail": "main 或 backup 未配置,容灾无从验证(生产至少配两个平台)"}
    provider = provider_of(os.getenv("MG_ROLE_MAIN", "")) or "aliyun"
    env_name = provider_key_env(provider)
    attempts: list[dict] = []
    original = llm._stream_once

    async def spy(*args, **kwargs):
        attempts.append({"model": args[2], "host": host_of(args[0])})
        async for delta in original(*args, **kwargs):
            yield delta

    saved = os.environ.get(env_name)
    os.environ[env_name] = "sk-invalid-deploy-check"
    llm._stream_once = spy
    try:
        text, _ttft, total = await collect(
            llm.stream_chat(SYSTEM, USER, role="main", fallback=True,
                            thinking=False, max_tokens=MAX_TOKENS),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001
        return {"role": "failover", "status": "fail",
                "detail": f"主用被打坏后整体失败({exc.__class__.__name__}: {exc}),备胎没接住",
                "hint": "检查 MG_ROLE_BACKUP 的平台 key 是否可用;备胎不通等于没有容灾"}
    finally:
        llm._stream_once = original
        if saved is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = saved

    if len(attempts) < 2:
        return {"role": "failover", "status": "fail",
                "detail": f"只尝试了 {len(attempts)} 次,没有触发切换(主用居然成功了?)",
                "hint": f"确认 {env_name} 覆盖生效;或主用平台对无效 key 仍返回 200(极不正常)"}
    first, last = attempts[0], attempts[-1]
    if (first["model"], first["host"]) == (last["model"], last["host"]):
        return {"role": "failover", "status": "fail",
                "detail": f"两次都打到 {first['model']} @ {first['host']},不是异平台备胎",
                "hint": "MG_ROLE_BACKUP 要指向**另一个平台**(多厂商容灾),同平台重试挡不住平台级故障"}
    if not text.strip():
        return {"role": "failover", "status": "fail",
                "detail": f"{last['model']} 接管了但没出正文",
                "hint": "备胎模型可能不支持当前 max_tokens/思考参数,换模型或去掉参数试"}
    return {"role": "failover", "status": "ok",
            "detail": f"{first['model']} 失败 → {last['model']} @ {last['host']} 接管 · "
                      f"{len(text)} 字 / {total:.2f}s"}


def _utf8() -> None:
    """Windows 控制台默认 GBK:不切 UTF-8 的话中文提示会变成 `???`(不影响判定)。"""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def _show(result: dict) -> None:
    status = result["status"]
    if status == "ok":
        print(f"{GREEN}[ OK ]{RESET} {result['role']}: {result['detail']}")
        return
    if status == "skip":
        print(f"{GREY}[SKIP]{RESET} {result['role']}: {result['detail']}")
        return
    print(f"{RED}[FAIL]{RESET} {result['role']}: {result['detail']}")
    if result.get("hint"):
        print(f"        {YELLOW}修复: {result['hint']}{RESET}")


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(description="LLM 连通性 / 容灾自检")
    parser.add_argument("--role", action="append", choices=ROLES, help="只测指定角色(可重复)")
    parser.add_argument("--timeout", type=float, default=120.0, help="单角色总超时(秒)")
    parser.add_argument("--failover", action="store_true", help="打坏主用,验证备胎接管")
    parser.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = parser.parse_args(argv)

    config.load_env()  # .env.local:服务器上通常没有这个文件,配置走 systemd Environment=
    roles = args.role or list(ROLES)
    results = [asyncio.run(probe_role(role, args.timeout)) for role in roles]
    if args.failover:
        results.append(asyncio.run(probe_failover(args.timeout)))

    embedding = embed.is_configured()
    failed = [item for item in results if item["status"] == "fail"]
    if args.json:
        print(json.dumps({
            "ok": not failed,
            "results": results,
            "embedding": {"configured": embedding,
                          "model": embed.model_name() if embedding else ""},
        }, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    print("=" * 64)
    print("  MathGuide · LLM 平台连通性自检(部署项 2.5)")
    print("=" * 64)
    for result in results:
        _show(result)
    print(f"{GREY}[i]{RESET} Embedding: "
          + (f"已配置 {embed.model_name()}" if embedding else "未配置(关键词检索模式,问答仍可用)"))
    if not args.failover:
        print(f"{GREY}[i]{RESET} 本轮没测容灾;生产上请再跑一次 --failover(打坏主用看备胎是否接管)")
    print("=" * 64)
    if failed:
        print(f"{RED}{len(failed)} 项失败{RESET}:按上面的「修复」逐条处理,别在部署窗口里赌")
        return 1
    skipped = sum(1 for item in results if item["status"] == "skip")
    print(f"{GREEN}全部通过{RESET}" + (f"(SKIP {skipped} 项:未配置的角色属预期)" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

