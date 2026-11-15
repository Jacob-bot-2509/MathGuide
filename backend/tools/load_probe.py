"""并发导出 / 内存峰值 / 长文档耗时探针(部署项 2.3 · 2.4 · 2.12)。

三件只有上了目标机才能回答的事,一条命令给出数字:

    2.3  长文档超时基线   --long-doc 60   60 节中文+公式长文档的真实渲染耗时,
                                         必须 < MG_PDF_TIMEOUT 的 60%(默认 120s → 72s)
    2.4  并发导出内存上限  --export 2      2 个并发 PDF 导出期间服务进程的 RSS 峰值,
                                         占「可用内存」的比例要 < 70%
    2.12 并发问答首字延迟  --chat 10       10 个并发 SSE 问答的首字 p50/p95 与失败率

为什么单独成脚本:这三项都需要**真实负载 + 真实机型**,本机测出来的数字对目标机
没有意义;把测法固定下来,换机器时重跑即可,不用每次现编命令。

内存怎么采:Linux 读 `/proc/<pid>/status` 的 `VmRSS`,macOS 退到 `ps -o rss=`,
不引入 psutil —— 部署机只该有标准库。`--pid 0` 自动找 uvicorn;找不到就只报延迟,
内存项标 SKIP(而不是假装测过)。

用法(backend 目录下):
    python tools/load_probe.py --long-doc 100          # 约 60 页(2.3)
    python tools/load_probe.py --export 2 --pid 0 --phone 13600136000 --password ******
    python tools/load_probe.py --chat 10 --pid 0 --phone 1... --password ... --phone 2... --password ...

并发与限流:聊天与导出共用「每用户 6 次/分」的滑动窗口限流。十并发只用一个账号会先撞
这条限制(429 `rate limited`),测出来的是限流而不是机器;所以 `--phone/--password` 可以
重复,脚本按请求轮询账号。导出闸门自己的 429 是 `pdf export busy`(带 Retry-After),
两者分开计数 —— 混在一起会把"我刷太快"读成"机器扛不住"。

退出码:0 = 通过;1 = 有失败项;2 = 参数或前置条件不成立(未选模式/登录失败)。
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# 本机/内网直连:不能让系统代理(Clash 之类)截胡 127.0.0.1 的请求 —— 这会把
# 「服务没起」和「代理吞了请求」混成同一种失败。
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))

RED, GREEN, YELLOW, GREY, RESET = "\033[91m", "\033[92m", "\033[93m", "\033[90m", "\033[0m"
QA_ITEMS = [{
    "question": "什么是函数极限?",
    "answer": "函数极限描述自变量趋于某点时函数值的趋势。例:lim(x→0) sin x / x = 1。",
}]
CHAT_PROMPT = "用一句话解释函数极限。"


def parse_rss_kb(status_text: str) -> int | None:
    """`/proc/<pid>/status` → VmRSS(KB)。取不到返回 None(不是 0:0 会被当成"测到了")。"""
    for line in status_text.splitlines():
        if line.startswith("VmRSS:"):
            parts = line.split()
            try:
                return int(parts[1])
            except (IndexError, ValueError):
                return None
    return None


def read_rss_kb(pid: int) -> int | None:
    """采样一次常驻内存(KB);不支持的平台返回 None。"""
    if pid <= 0:
        return None
    status = Path(f"/proc/{pid}/status")
    if status.exists():
        try:
            return parse_rss_kb(status.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
    try:  # macOS / BSD:没有 /proc,ps 的 rss 单位就是 KB
        out = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                             capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = (out.stdout or b"").decode("utf-8", "replace").strip()
    try:
        return int(text.splitlines()[0])
    except (IndexError, ValueError):
        return None


def find_server_pid(pattern: str = "uvicorn main:app") -> int:
    """`--pid 0`:按命令行找后端进程。找不到返回 0(调用方据此把内存项标 SKIP)。"""
    try:
        out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return 0
    for token in (out.stdout or b"").decode("utf-8", "replace").split():
        if token.strip().isdigit():
            return int(token)
    return 0


def _meminfo_kb(text: str, key: str) -> int | None:
    for line in text.splitlines():
        if line.startswith(f"{key}:"):
            try:
                return int(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def mem_available_kb(meminfo_text: str) -> int | None:
    """`MemAvailable`(KB):判「还有多少余量」用它,不用 MemFree(缓存会把后者压到很小)。"""
    return _meminfo_kb(meminfo_text, "MemAvailable")


def total_mem_kb(meminfo_text: str) -> int | None:
    return _meminfo_kb(meminfo_text, "MemTotal")


def percentile(values: list[float], pct: float) -> float:
    """最近秩法(nearest-rank):样本个位数时不要插值,那只是把噪声包装成精度。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def mem_verdict(peak_kb: int | None, limit_kb: int | None, limit_pct: float) -> tuple[bool, str]:
    """峰值内存 → (是否达标, 人话结论)。没有分母时给 SKIP 文案,绝不默认 PASS。"""
    if not peak_kb:
        return True, "内存未采样(SKIP:--pid 没给或平台不支持,结论只剩延迟)"
    if not limit_kb:
        return True, f"RSS 峰值 {peak_kb / 1024:.0f} MB(可用内存未知,无法算比例)"
    share = peak_kb / limit_kb * 100
    return share <= limit_pct, (f"RSS 峰值 {peak_kb / 1024:.0f} MB / 可用 "
                                f"{limit_kb / 1024:.0f} MB = {share:.1f}%(阈值 {limit_pct:.0f}%)")


_LONG_PARAS = (
    "这一节讨论极限、连续与可微三者的关系。函数在一点连续的必要条件是左右极限相等;"
    "可微必连续,但连续不一定可微(例如绝对值函数在原点)。下面用一条长公式把排版推到"
    "与真实长文档同一量级,以便测出渲染耗时的上界。",
    "讨论一致连续时,重要的是「同一个 δ 要对整个区间都管用」。开区间上一致连续意味着"
    "函数不能在该区间上无限加速:例如 1/x 在 (0,1) 上连续但非一致连续,而它在 [1,∞) 上"
    "就是一致连续的。这类反例在教材里通常配图说明,导出时必须保证图与公式都不掉行。",
    "级数收敛的判别需要区分绝对收敛与条件收敛。绝对收敛对重排不变,条件收敛则可通过"
    "重排得到任意实数(Riemann 重排定理)。排版时这些结论常与行间公式混排,是检验"
    "「中文 + 公式 + 长段落」混排是否稳定的好样本。",
    "中值定理把「平均变化率」与「某点的瞬时变化率」接起来:罗尔、拉格朗日、柯西三者的"
    "差别只在附加条件。证明题里常见的写法是先构造辅助函数,再用罗尔定理收尾;辅助函数的"
    "构造过程恰好是一段需要与公式交替排版的长文本。",
    "多元函数的可微比偏导存在强得多。偏导存在不足以保证可微,还需要增量与线性主部之差"
    "是关于增量范数的高阶无穷小。教材里通常用一条带 o(‖h‖) 的行间公式表达这一点,"
    "导出时这类公式宽度接近页宽,是最容易溢出的排版对象。",
    "定积分的存在性由达布和的上确界与下确界相等给出。可积函数类包括连续函数、单调函数"
    "与只有有限个间断点的有界函数。证明里经常出现分点加密与振幅估计,格式上表现为"
    "「一段文字 + 一个不等式 + 一段文字」的交替,正好压测分页逻辑。",
)
_LONG_FORMULAS = (
    r"$\lim_{n\to\infty}\sum_{k=1}^{n}\frac{1}{k^{2}}=\frac{\pi^{2}}{6}$",
    r"$\int_{0}^{1}\frac{\ln x}{1-x}\,dx=-\frac{\pi^{2}}{6}$",
    r"$\forall\varepsilon>0\ \exists\delta>0:\ |x-x_0|<\delta\Rightarrow|f(x)-f(x_0)|<\varepsilon$",
)


def build_long_doc(sections: int) -> dict:
    """造一份 N 节的中文+公式长文档(2.3 的负载),每节约一页。

    刻意用「多段落 + 行间公式」而不是纯文字:KaTeX 排版才是耗时大头,纯文字测出来的
    数字会让人误以为机器很快。三个段落/三条公式轮换,避免全文重复导致 PDF 体积失真。
    """
    total = max(1, sections)
    body = []
    for index in range(total):
        paragraphs = [_LONG_PARAS[(index + offset) % len(_LONG_PARAS)]
                      for offset in range(len(_LONG_PARAS))]
        paragraphs += [f"公式:{_LONG_FORMULAS[(index + offset) % len(_LONG_FORMULAS)]}"
                       for offset in range(2)]
        body.append({"heading": f"{index + 1}. 极限、连续与级数", "paragraphs": paragraphs})
    return {
        "title": f"长文档渲染基线({len(body)} 节)",
        "abstract": "部署项 2.3 的耗时基线样张:中文段落 + 行间公式 + 多节。",
        "sections": body,
        "references": [{"id": 1, "title": "基线来源", "source": "local", "url": ""}],
    }


def count_pages(data: bytes) -> int:
    """粗估页数:数 `/Type /Page`(不含 `/Type /Pages` 这个页树节点)。

    只为让人对上"这是不是长文档",不追求 PDF 解析器的准确度 —— 上 pypdf 会拖慢探测,
    而且这里量的是耗时,不是文档结构。
    """
    if not data:
        return 0
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


class RssSampler:
    """后台采样常驻内存,`with` 块结束时拿到峰值。

    注意:峰值不是「最后一次读数」—— 导出结束后浏览器进程退出,内存会掉回去,
    只有全程采样才能看到真实的尖峰。
    """

    def __init__(self, pid: int, interval: float = 0.2) -> None:
        self.pid = pid
        self.interval = interval
        self.peak = 0
        self.samples = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _sample(self) -> None:
        kb = read_rss_kb(self.pid)
        if kb:
            self.samples += 1
            self.peak = max(self.peak, kb)

    def _loop(self) -> None:
        while not self._stop.wait(self.interval):
            self._sample()

    def __enter__(self) -> RssSampler:
        self._sample()  # 先来一次:极短的任务可能一次都采不到
        if self.pid > 0:
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        return self

    def __exit__(self, *exc_info) -> bool:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._sample()
        return False


@dataclass
class Ctx:
    """一次探测的上下文(token 优先;没有就登录换一个)。"""

    base: str
    token: str = ""
    timeout: float = 180.0
    headers: dict = field(default_factory=dict)

    def url(self, path: str) -> str:
        return self.base.rstrip("/") + path

    def call(self, method: str, path: str, body: object = None,
             timeout: float | None = None) -> tuple[int, dict, bytes]:
        """发一次请求 → (状态码, 头部, 正文)。HTTPError 也当普通响应(状态码要断言)。"""
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"User-Agent": "mg-load-probe", "Accept": "*/*", **self.headers}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(self.url(path), data=data, method=method, headers=headers)
        # 每个请求独立 opener:OpenerDirector 不保证线程安全,而这里是多线程并发
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout or self.timeout) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers or {}), exc.read() or b""


def login(ctx: Ctx, phone: str, password: str) -> bool:
    """用已有账号换 token(不注册:探测脚本不该往线上库塞账号)。"""
    status, _headers, body = ctx.call("POST", "/api/auth/login",
                                      {"phone": phone, "password": password}, timeout=20)
    if status != 200:
        print(f"{RED}[FAIL]{RESET} 登录失败({status}): {body[:160]!r}")
        print(f"        {YELLOW}修复:--phone/--password 用线上已有账号;或直接给 --token{RESET}")
        return False
    try:
        ctx.token = str(json.loads(body).get("token") or "")
    except json.JSONDecodeError:
        ctx.token = ""
    if not ctx.token:
        print(f"{RED}[FAIL]{RESET} 登录响应里没有 token")
        return False
    return True


def read_meminfo() -> str:
    """`/proc/meminfo` 全文;非 Linux 返回空串(内存比例就退化成 SKIP)。"""
    try:
        return Path("/proc/meminfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def run_long_doc(sections: int, budget_pct: float = 60.0) -> dict:
    """2.3:本地渲染一份 N 节长文档,与 `MG_PDF_TIMEOUT` 对比。

    走本地渲染而不是打 HTTP:量的是**这台机器的渲染能力**,不掺网络与鉴权,
    也不受并发闸门限流影响。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import doc  # noqa: E402 与后端同一实现(doc.render_pdf_bytes)

    timeout = doc._pdf_timeout()
    budget = timeout * budget_pct / 100
    started = time.monotonic()
    data = doc.render_pdf_bytes(build_long_doc(sections), "zh", "长文档基线")
    elapsed = time.monotonic() - started
    valid = bool(data) and data.startswith(b"%PDF")
    result = {
        "mode": "long_doc", "sections": max(1, sections), "seconds": elapsed,
        "pages": count_pages(data or b""), "bytes": len(data or b""),
        "timeout": timeout, "budget_pct": budget_pct, "budget": budget,
        "ok": valid and elapsed <= budget,
    }
    if not valid:
        result["hint"] = "渲染返回空:先在目标机跑 python tools/check_pdf.py(浏览器/字体/沙箱)"
    elif elapsed > budget:
        result["hint"] = (f"超过预算:{elapsed:.0f}s > {budget:.0f}s。把 MG_PDF_TIMEOUT 调大"
                          f"(低配 VPS 建议 300),或降低单份导出体量")
    return result


def classify_429(body: bytes) -> str:
    """429 的**来源**决定结论对不对:导出闸门是容量信号,接口限流只是测量无效。

    `doc`/`docgen` 复用 chat 的滑动窗口限流(每用户 6 次/分,回 `rate limited`);
    导出并发闸门回 `pdf export busy`(带 Retry-After)。两者混为一谈会把"我刷太快"
    当成"机器扛不住",于是把 MG_PDF_CONCURRENCY 调到错误的方向。
    """
    text = (body or b"")[:200].decode("utf-8", "replace").lower()
    if "pdf export busy" in text:
        return "gate"
    if "rate limited" in text:
        return "ratelimit"
    return "unknown"


def export_once(ctx: Ctx, timeout: float) -> dict:
    """一次 PDF 导出;失败也返回结果,不让一个线程炸掉整轮。"""
    started = time.monotonic()
    try:
        status, headers, body = ctx.call("POST", "/api/doc/qa",
                                         {"items": QA_ITEMS, "format": "pdf", "lang": "zh"},
                                         timeout=timeout)
    except Exception as exc:  # noqa: BLE001 连接被重置/超时都要落成一条结果
        return {"ok": False, "status": 0, "seconds": time.monotonic() - started,
                "bytes": 0, "retry_after": "", "kind": "", "error": f"{exc.__class__.__name__}: {exc}"}
    retry_after = next((v for k, v in headers.items() if k.lower() == "retry-after"), "")
    return {"ok": status == 200 and body.startswith(b"%PDF"), "status": status,
            "seconds": time.monotonic() - started, "bytes": len(body),
            "retry_after": retry_after, "kind": classify_429(body) if status == 429 else "",
            "error": ""}


def _ctx_for(base: str, tokens: list[str], index: int, timeout: float) -> Ctx:
    """第 index 个并发请求用哪个账号:轮询分配,避免单账号撞「6 次/分」的接口限流。"""
    token = tokens[index % len(tokens)] if tokens else ""
    return Ctx(base=base, token=token, timeout=timeout)


def run_exports(base: str, tokens: list[str], count: int, pid: int, limit_kb: int | None,
                limit_pct: float, timeout: float) -> dict:
    """2.4:并发导出,全程采样 RSS 峰值。"""
    with RssSampler(pid) as sampler:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(
                lambda i: export_once(_ctx_for(base, tokens, i, timeout), timeout), range(count)))
        wall = time.monotonic() - started
    seconds = [item["seconds"] for item in results]
    gated = [item for item in results if item["kind"] == "gate"]
    limited = [item for item in results if item["kind"] == "ratelimit"]
    unknown_429 = [item for item in results if item["status"] == 429 and item["kind"] == "unknown"]
    failed = [item for item in results if not item["ok"] and item["status"] != 429]
    failed += unknown_429
    mem_ok, mem_detail = mem_verdict(sampler.peak or None, limit_kb, limit_pct)
    result = {
        "mode": "export", "count": count, "wall": wall, "accounts": max(1, len(tokens)),
        "p50": percentile(seconds, 50), "p95": percentile(seconds, 95),
        "max": max(seconds), "ok_count": len(results) - len(gated) - len(limited) - len(failed),
        "gated": len(gated), "limited": len(limited), "failed": len(failed),
        "peak_kb": sampler.peak, "samples": sampler.samples, "mem_detail": mem_detail,
        "statuses": [item["status"] for item in results],
        "retry_after": next((item["retry_after"] for item in gated if item["retry_after"]), ""),
        "errors": [item["error"] for item in failed if item["error"]],
        # 接口限流让这次测量无效,必须判失败;导出闸门的 429 是容量信号,不算失败
        "ok": mem_ok and not failed and not limited,
    }
    if limited:
        result["hint"] = (f"{len(limited)} 个请求被接口限流(每用户 6 次/分,与导出闸门无关):"
                          "这次测量无效。加账号(--phone/--password 可重复)或隔 60 秒再跑")
    elif gated:
        result["hint"] = (f"{len(gated)} 个请求被导出闸门挡住(429):并发数超过 MG_PDF_CONCURRENCY "
                          f"时这是正常表现;排队上限见 MG_PDF_QUEUE,"
                          f"重试等待见 Retry-After={result['retry_after'] or '(未带)'}")
    elif not mem_ok:
        result["hint"] = ("内存峰值超过阈值:把 MG_PDF_CONCURRENCY 降到 1,或换更大内存的机器;"
                          "浏览器实例是常驻开销,不是泄漏")
    elif failed:
        result["hint"] = "有请求非 200:先跑 python tools/check_pdf.py,再看后端日志"
    return result


def chat_once(ctx: Ctx, prompt: str, timeout: float) -> dict:
    """一次 SSE 问答:只记首字与帧数(不解析正文,避免把探针变成评测脚本)。"""
    started = time.monotonic()
    first: float | None = None
    frames = 0
    data = json.dumps({"prompt": prompt}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream",
               "User-Agent": "mg-load-probe"}
    if ctx.token:
        headers["Authorization"] = f"Bearer {ctx.token}"
    request = urllib.request.Request(ctx.url("/api/chat/stream"), data=data, method="POST",
                                     headers=headers)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            for raw in response:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if not payload or payload == "[DONE]":
                    continue
                if first is None:
                    first = time.monotonic() - started
                frames += 1
    except urllib.error.HTTPError as exc:
        body = exc.read() or b""
        return {"ok": False, "status": exc.code, "seconds": time.monotonic() - started,
                "ttft": None, "frames": 0, "kind": classify_429(body) if exc.code == 429 else "",
                "error": f"HTTP {exc.code}: {body[:80]!r}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "status": 0, "seconds": time.monotonic() - started,
                "ttft": None, "frames": 0, "kind": "", "error": f"{exc.__class__.__name__}: {exc}"}
    return {"ok": frames > 0, "status": 200, "seconds": time.monotonic() - started,
            "ttft": first, "frames": frames, "kind": "", "error": ""}


def run_chat(base: str, tokens: list[str], count: int, pid: int, limit_kb: int | None,
             limit_pct: float, timeout: float, prompt: str) -> dict:
    """2.12:并发问答,看首字 p50/p95、失败率与内存峰值。"""
    with RssSampler(pid) as sampler:
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(
                lambda i: chat_once(_ctx_for(base, tokens, i, timeout), prompt, timeout),
                range(count)))
        wall = time.monotonic() - started
    ttfts = [item["ttft"] for item in results if item["ttft"] is not None]
    limited = [item for item in results if item["kind"] == "ratelimit"]
    failed = [item for item in results if not item["ok"] and item["kind"] != "ratelimit"]
    mem_ok, mem_detail = mem_verdict(sampler.peak or None, limit_kb, limit_pct)
    result = {
        "mode": "chat", "count": count, "wall": wall, "accounts": max(1, len(tokens)),
        "p50": percentile(ttfts, 50), "p95": percentile(ttfts, 95),
        "max": max(ttfts) if ttfts else 0.0,
        "ok_count": len(results) - len(failed) - len(limited),
        "failed": len(failed), "limited": len(limited),
        "peak_kb": sampler.peak, "samples": sampler.samples,
        "mem_detail": mem_detail, "statuses": [item["status"] for item in results],
        "errors": [item["error"] for item in failed if item["error"]],
        "ok": mem_ok and not failed and not limited and bool(ttfts),
    }
    if limited:
        result["hint"] = (f"{len(limited)} 个请求被接口限流(每用户 6 次/分):并发数不能只靠多线程,"
                          "要给更多账号(--phone/--password 可重复)或隔 60 秒再跑")
    elif failed:
        result["hint"] = ("有问答失败:先跑 tools/smoke_deploy.py 确认基线;并发下失败多为额度/"
                          "上游首字超时")
    elif not mem_ok:
        result["hint"] = "内存峰值偏高:单 worker 下额度与缓存都是进程内实现,持续压测只会涨内存"
    return result


def report(result: dict) -> None:
    """把一项探测结果打成人能读的一段(判定 + 数字 + 处置)。"""
    tag = f"{GREEN}[ OK ]{RESET}" if result["ok"] else f"{RED}[FAIL]{RESET}"
    mode = result["mode"]
    if mode == "long_doc":
        print(f"{tag} 2.3 长文档:{result['sections']} 节 · 约 {result['pages']} 页 · "
              f"{result['bytes'] / 1024:.0f} KB → 渲染 {result['seconds']:.1f}s "
              f"(预算 {result['budget']:.0f}s = MG_PDF_TIMEOUT {result['timeout']:.0f}s 的 "
              f"{result['budget_pct']:.0f}%)")
    elif mode == "export":
        print(f"{tag} 2.4 并发导出 ×{result['count']}(账号 {result['accounts']}):"
              f"成功 {result['ok_count']} · 闸门 429 {result['gated']} · "
              f"限流 429 {result['limited']} · 失败 {result['failed']} · "
              f"p50 {result['p50']:.1f}s / max {result['max']:.1f}s · 总耗时 {result['wall']:.1f}s")
        print(f"        内存:{result['mem_detail']}(采样 {result['samples']} 次)")
    else:
        print(f"{tag} 2.12 并发问答 ×{result['count']}(账号 {result['accounts']}):"
              f"成功 {result['ok_count']} · 限流 429 {result['limited']} · "
              f"失败 {result['failed']} · 首字 p50 {result['p50']:.2f}s / "
              f"p95 {result['p95']:.2f}s · 总耗时 {result['wall']:.1f}s")
        print(f"        内存:{result['mem_detail']}(采样 {result['samples']} 次)")
    for error in result.get("errors", [])[:3]:
        print(f"        {GREY}{error}{RESET}")
    if result.get("hint"):
        print(f"        {YELLOW}处置: {result['hint']}{RESET}")


def _utf8() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    _utf8()
    parser = argparse.ArgumentParser(description="并发导出 / 内存峰值 / 长文档耗时探针")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="服务地址(并发模式用)")
    parser.add_argument("--token", default="", help="已有登录 token(优先于账号密码)")
    parser.add_argument("--phone", action="append", default=[], metavar="PHONE",
                        help="已有账号手机号(可重复:每个账号 6 次/分,十并发要多个)")
    parser.add_argument("--password", action="append", default=[], metavar="PWD",
                        help="与 --phone 一一对应的密码")
    parser.add_argument("--pid", type=int, default=0, help="后端进程 PID(0=自动找,-1=不采样)")
    parser.add_argument("--mem-limit", type=float, default=70.0, help="RSS 峰值占可用内存上限(%%)")
    parser.add_argument("--timeout", type=float, default=180.0, help="单请求超时(秒)")
    parser.add_argument("--export", type=int, default=0, metavar="N", help="并发 PDF 导出数(2.4)")
    parser.add_argument("--chat", type=int, default=0, metavar="N", help="并发问答数(2.12)")
    parser.add_argument("--long-doc", type=int, nargs="?", const=60, default=0, metavar="N",
                        help="长文档节数(2.3,给 --long-doc 不带值=60)")
    parser.add_argument("--prompt", default=CHAT_PROMPT, help="问答探测用的提问")
    parser.add_argument("--json", action="store_true", help="只输出 JSON(存档/接监控)")
    args = parser.parse_args(argv)

    if not (args.export or args.chat or args.long_doc):
        parser.error("至少选一个模式:--long-doc [N] / --export N / --chat N")

    ctx = Ctx(base=args.base_url, token=args.token, timeout=args.timeout)
    tokens: list[str] = [args.token] if args.token else []
    results: list[dict] = []
    if not args.json:
        print("=" * 68)
        print("  MathGuide · 负载探针(部署项 2.3 / 2.4 / 2.12)")
        print("=" * 68)

    if args.long_doc:
        results.append(run_long_doc(args.long_doc))

    if args.export or args.chat:
        if not tokens:
            if len(args.phone) != len(args.password) or not args.phone:
                print(f"{RED}[FAIL]{RESET} 并发探测需要登录:给 --token,或成对给 "
                      f"--phone/--password(各账号密码个数要一致)")
                return 2
            for phone, password in zip(args.phone, args.password, strict=True):
                ctx.token = ""
                if not login(ctx, phone, password):
                    return 2
                tokens.append(ctx.token)
            if not args.json:
                print(f"{GREY}[i]{RESET} 已登录 {len(tokens)} 个账号(每账号 6 次/分)")
        ctx.token = ""  # 逐请求按账号轮询,别让主线程的 token 粘住

    pid = args.pid
    if pid == 0:
        pid = find_server_pid()
        if pid and not args.json:
            print(f"{GREY}[i]{RESET} 自动找到后端进程 PID={pid}")
        elif not args.json:
            print(f"{GREY}[i]{RESET} 没找到后端进程(可显式 --pid N);内存项将 SKIP")
    meminfo = read_meminfo()
    limit_kb = mem_available_kb(meminfo) if meminfo else None
    total_kb = total_mem_kb(meminfo) if meminfo else None
    if total_kb and limit_kb and not args.json:
        print(f"{GREY}[i]{RESET} 内存:总 {total_kb / 1024 / 1024:.1f} GB · "
              f"可用 {limit_kb / 1024 / 1024:.1f} GB(阈值取可用量的 {args.mem_limit:.0f}%)")

    if args.export:
        results.append(run_exports(args.base_url, tokens, max(1, args.export), pid, limit_kb,
                                   args.mem_limit, args.timeout))
    if args.chat:
        results.append(run_chat(args.base_url, tokens, max(1, args.chat), pid, limit_kb,
                                args.mem_limit, args.timeout, args.prompt))

    failed = [item for item in results if not item["ok"]]
    if args.json:
        print(json.dumps({"ok": not failed, "results": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0

    for item in results:
        report(item)
    print("=" * 68)
    if failed:
        print(f"{RED}{len(failed)} 项未达标{RESET}:结论要么改配置(MG_PDF_CONCURRENCY / "
              f"MG_PDF_TIMEOUT),要么记进已知限制")
        return 1
    print(f"{GREEN}全部达标{RESET}:把这几行数字抄进部署记录,下次换机器时对照")
    return 0


if __name__ == "__main__":
    sys.exit(main())




