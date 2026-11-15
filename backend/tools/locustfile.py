"""压测脚本(Locust),与 `load_probe.py` 互补:一个判过没过,一个给曲线。

分工:
    load_probe.py   上机验收:按项目判据给 PASS/FAIL/SKIP,能读服务进程 RSS 峰值,
                    把两类 429 分开计数,但**不产出压力曲线**。
    locustfile.py   压测:模拟 N 个并发用户持续打,产出 QPS / 分位延迟 / HTML 报告;
                    同样把两类 429 分开 —— 导出闸门的 429 是容量信号(记成功,单列一行),
                    每用户限流的 429 是「测法太密」(记失败、单列一行,本轮并发结论无效)。

两类 429 必须分开读:
    {"detail": "pdf export busy, retry later"} + Retry-After  → 闸门在工作,重试即可(容量信号)
    {"detail": "rate limited"}                                → 撞的是每用户 6 次/分(测法太密)

测容量(天花板)前必须先关掉后端那条每用户限流:用 `MG_CHAT_RATE_MAX=0` 起后端。
它在贵的活之前判定,不关掉的话同一账号的并发请求先撞 `rate limited`,导出的
`pdf export busy` 永远不会出现 —— 量到的是限流,不是机器上限。两个阶段分开跑:
先 `MG_CHAT_RATE_MAX=0` 量容量,再恢复默认(删掉该变量 = 6 次/60 秒)验证限流咬得住。

依赖:locust **不在** requirements-dev.txt 里(它会拖进 gevent,各解释器版本的 wheel 覆盖
不一致,不该让 CI 承担),按需 `pip install locust`。

用法(先在 backend/ 下起后端:`uvicorn main:app --port 8000`):

    # A 静态吞吐(不打模型、不花钱):health + session
    python -m locust -f tools/locustfile.py --headless -u 50 -r 10 -t 30s \
        --tags static --host http://127.0.0.1:8000
    # B 问答并发(真打模型,注意费用;测容量时后端先 MG_CHAT_RATE_MAX=0)
    export MG_LOCUST_TOKENS="tok1,tok2,tok3"        # PowerShell: $env:MG_LOCUST_TOKENS="..."
    python -m locust -f tools/locustfile.py --headless -u 6 -r 6 -t 60s --tags chat --host ...
    # C 导出并发(验证 MG_PDF_CONCURRENCY 闸门)
    python -m locust -f tools/locustfile.py --headless -u 12 -r 12 -t 60s --tags export --host ...
    # D 要图表就用 Web UI:去掉 --headless,打开 http://localhost:8089 手动加减用户

凭据规则:**一个虚拟用户对一个账号**。`-u` 超过凭据数就会复用账号,先撞「每用户 6 次/分」,
     测出来的是限流而不是机器(结束时 `rate_429` 会 >0 并给出提示)。
        MG_LOCUST_TOKENS="tok1,tok2"          直传 token:免登录,也不撞认证接口的 10 次/分/IP
        MG_LOCUST_ACCOUNTS="手机号:密码,..."   没有 token 时用,test_start 里统一登录一次
     chat / export 在完全没有凭据时**直接退出**:否则两个任务都空转,跑出一个
     「0 请求 · 0 失败」的假结果(比报错更危险)。static 不需要凭据,session 一项会跳过。

Windows 注意:locust 会解析**当前目录**的 `pyproject.toml`,而 `backend/pyproject.toml` 是 UTF-8
     中文注释,中文 Windows 的 GBK locale 读它会直接报 `Couldn't parse TOML file`(连 `--version`
     都跑不起来)。先 `$env:PYTHONUTF8="1"`,或换到不含 pyproject.toml 的目录再跑;
     Linux 的 locale 是 UTF-8,不受影响。
"""
from __future__ import annotations

import itertools
import json
import os
import threading

import requests
from locust import HttpUser, between, events, tag, task

CHAT_PROMPT = "用一句话解释函数极限。"
EXPORT_CONTENT = (
    "函数极限的定义:设函数 f 在点 x0 的某个去心邻域内有定义,若存在常数 A,"
    "使得对任意 epsilon > 0,总存在 delta > 0,当 0 < |x - x0| < delta 时,"
    "都有 |f(x) - A| < epsilon,则称 A 为 f 当 x 趋于 x0 时的极限,记作 "
    "lim_{x->x0} f(x) = A。极限是导数与积分的基础,数列极限与函数极限通过"
    "海涅定理相互转化。"
)

_tokens: list[str] = []
_accounts: list[tuple[str, str]] = []
_counter = itertools.count()
_lock = threading.Lock()
stats = {"gate_429": 0, "rate_429": 0, "chat_ok": 0, "export_ok": 0}


def _load_credentials() -> None:
    raw_tokens = os.getenv("MG_LOCUST_TOKENS", "").strip()
    if raw_tokens:
        _tokens.extend(t.strip() for t in raw_tokens.split(",") if t.strip())
    for item in os.getenv("MG_LOCUST_ACCOUNTS", "").split(","):
        if ":" in item:
            phone, pwd = item.split(":", 1)
            _accounts.append((phone.strip(), pwd.strip()))


def _login_all(host: str) -> None:
    """统一登录:一次拿全 token,避免每个虚拟用户各登录一次撞认证 10 次/分/IP。"""
    if _tokens or not _accounts:
        return
    session = requests.Session()
    session.trust_env = False  # 不能让系统代理(Clash 之类)截胡 127.0.0.1
    for phone, pwd in _accounts:
        try:
            resp = session.post(
                f"{host}/api/auth/login",
                json={"method": "password", "phone": phone, "password": pwd},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise SystemExit(f"[locust] 登录请求失败({phone}): {exc}") from exc
        token = (resp.json() or {}).get("token", "") if resp.status_code == 200 else ""
        if not token:
            raise SystemExit(
                f"[locust] 登录失败({phone}): {resp.status_code} {resp.text[:200]}")
        _tokens.append(token)


def _classify(resp) -> str:
    """只看状态码;仅错误响应才读 body(流式响应读 body 会把 SSE 流吃掉)。"""
    if resp.status_code == 200:
        return "ok"
    if resp.status_code == 429:
        text = resp.text or ""
        if "pdf export busy" in text:
            return "gate"
        if "rate limited" in text:
            return "rate"
    return "err"


def _bump(key: str) -> None:
    with _lock:
        stats[key] += 1


def _selected_tags(environment) -> set[str]:
    """--tags 选中的标签集合;拿不到返回空集(当作「全部任务」)。"""
    options = getattr(environment, "parsed_options", None)
    return {str(t).strip() for t in (getattr(options, "tags", None) or [])}


@events.test_start.add_listener
def _on_test_start(environment, **_kwargs) -> None:
    _load_credentials()
    _login_all(environment.host or "http://127.0.0.1:8000")
    tags = _selected_tags(environment)
    print(f"[locust] 凭据: tokens={len(_tokens)} accounts={len(_accounts)}"
          f" tags={sorted(tags) if tags else ['全部']}")
    if not _tokens and tags & {"chat", "export"}:
        raise SystemExit(
            "[locust] chat/export 需要登录凭据:设 MG_LOCUST_TOKENS(逗号分隔 token)"
            ' 或 MG_LOCUST_ACCOUNTS("手机号:密码,...")。没有凭据时这两个任务会全部'
            "空转,跑出「0 请求 · 0 失败」的假结果。")


@events.test_stop.add_listener
def _on_test_stop(environment, **_kwargs) -> None:
    print("[locust] 分类计数: " + json.dumps(stats, ensure_ascii=False))
    print("[locust] 判读: gate_429>0 = 导出闸门在工作(正常);"
          " rate_429>0 = 撞了每用户 6 次/分,本轮并发结论无效,加账号重跑。")
    total = getattr(getattr(environment, "stats", None), "total", None)
    if total is not None and not total.num_requests:
        print("[locust] 警告: 本轮 0 请求 —— 查 --tags 是否与要压的任务匹配、是否带了凭据。")


class MathGuideUser(HttpUser):
    """一个虚拟用户 = 一个账号;wait_time 决定的是「用户节奏」,不是服务端上限。"""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        with _lock:
            index = next(_counter)
        self.token = _tokens[index % len(_tokens)] if _tokens else ""

    @property
    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @tag("static")
    @task(6)
    def health(self) -> None:
        with self.client.get("/api/health", name="/api/health", catch_response=True) as resp:
            if resp.status_code == 200:
                resp.success()
            else:
                resp.failure(f"health {resp.status_code}")

    @tag("static")
    @task(2)
    def session(self) -> None:
        if not self.token:
            return
        with self.client.get("/api/auth/session", headers=self.auth,
                             name="/api/auth/session", catch_response=True) as resp:
            kind = _classify(resp)
            if kind == "rate":
                _bump("rate_429")
                resp.request_meta["name"] = "/api/auth/session [rate-429]"
                resp.failure("rate limited")
            elif kind != "ok":
                resp.failure(f"session {resp.status_code}")
            else:
                resp.success()

    @tag("chat")
    @task(2)
    def chat(self) -> None:
        if not self.token:
            return
        body = {"prompt": CHAT_PROMPT, "workspace": "learn"}
        with self.client.post("/api/chat/stream", json=body, headers=self.auth,
                              stream=True, catch_response=True, timeout=120,
                              name="/api/chat/stream") as resp:
            kind = _classify(resp)
            if kind == "rate":
                _bump("rate_429")
                resp.request_meta["name"] = "/api/chat/stream [rate-429]"
                resp.failure("rate limited(每用户 6 次/分,本轮测量无效)")
                return
            if kind != "ok":
                resp.failure(f"chat {resp.status_code}")
                return
            try:  # 读到 [DONE] 才算完成,响应时间 = 整段回答时长
                for line in resp.iter_lines():
                    if line and b"[DONE]" in line:
                        break
            except Exception as exc:  # 客户端中断/上游断开要算失败,不能静默
                resp.failure(f"stream broken: {exc}")
                return
            _bump("chat_ok")
            resp.success()

    @tag("export")
    @task(1)
    def export_pdf(self) -> None:
        if not self.token:
            return
        body = {"content": EXPORT_CONTENT, "lang": "zh"}
        with self.client.post("/api/doc/export", json=body, headers=self.auth,
                              catch_response=True, timeout=180,
                              name="/api/doc/export") as resp:
            kind = _classify(resp)
            if kind == "gate":  # 容量信号:记成功,但单列一行,免得被读成故障
                _bump("gate_429")
                resp.request_meta["name"] = "/api/doc/export [gate-429]"
                resp.success()
                return
            if kind == "rate":
                _bump("rate_429")
                resp.request_meta["name"] = "/api/doc/export [rate-429]"
                resp.failure("rate limited(每用户 6 次/分,本轮测量无效)")
                return
            if kind != "ok":
                resp.failure(f"export {resp.status_code}")
                return
            if not resp.content.startswith(b"%PDF"):
                resp.failure("响应不是 PDF")
                return
            _bump("export_ok")
            resp.success()
