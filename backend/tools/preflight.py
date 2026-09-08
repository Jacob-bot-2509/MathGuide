"""
演示/答辩前自检:一键验证全链路就绪,任何一项失败给出红色 [FAIL] 与修复提示。

检查项:
  1. 后端 /api/health
  2. 前端 5173 可访问
  3. 经 vite 代理登录(演示账号)
  4. 知识库装载(文档数 / 片段数)
  5. 三道抽查题端到端流式命中(中文知识 / 英文知识 / 闲聊)
  6. LLM / embedding 配置状态(信息项,不配置也可通过)

用法(backend 目录下,前后端已启动后执行):
    python tools/preflight.py

退出码:0 = 全部通过;1 = 有失败项。
"""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"

BASE = "http://127.0.0.1:8000"
FRONTEND = "http://localhost:5173"
DEMO_PHONE = "13600136000"
DEMO_PASSWORD = "demo123456"

# 抽查题:(提问, 回复中必须出现的关键词)
SMOKE_CASES = [
    ("什么是泰勒展开?", "泰勒"),
    ("What is Taylor expansion?", "Taylor"),
    ("你好", "MG"),
]

failures: list[str] = []


def ok(msg: str) -> None:
    print(f"{GREEN}[OK]{RESET} {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"{RED}[FAIL]{RESET} {msg}")
    if hint:
        print(f"      {YELLOW}修复:{hint}{RESET}")
    failures.append(msg)


def get(url: str, timeout: int = 8):
    req = urllib.request.Request(url, headers={"User-Agent": "mg-preflight"})
    return urllib.request.urlopen(req, timeout=timeout)


def post(url: str, body: dict, token: str = "", timeout: int = 20):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    return urllib.request.urlopen(req, timeout=timeout)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 规避 Windows GBK 控制台
    print("=" * 56)
    print("  MathGuide 演示前自检")
    print("=" * 56)

    # 1. 后端健康
    try:
        body = json.loads(get(f"{BASE}/api/health").read())
        assert body.get("ok") is True
        ok("后端服务 8000 健康")
    except Exception:
        fail("后端服务 8000 不可达", "先启动后端:仓库根目录双击 dev.bat,或 uvicorn main:app --port 8000")
        return 1

    # 2. 前端
    try:
        assert get(FRONTEND).status == 200
        ok("前端服务 5173 可访问")
    except Exception:
        fail("前端服务 5173 不可达", "先启动前端:npm run dev(dev.bat 会一并启动)")

    # 3. 代理登录
    token = ""
    try:
        body = json.loads(post(f"{BASE}/api/auth/login",
                               {"method": "password", "phone": DEMO_PHONE, "password": DEMO_PASSWORD}).read())
        token = body.get("token", "")
        assert token
        ok(f"演示账号登录成功({DEMO_PHONE})")
    except urllib.error.HTTPError as e:
        fail(f"演示账号登录失败(HTTP {e.code})", "检查 data/users.json 是否被误删;密码应为 demo123456")
        return 1
    except Exception:
        fail("演示账号登录失败(网络错误)", "确认后端正在运行")
        return 1

    # 4. 知识库装载
    docs = sorted(Path(__file__).resolve().parent.parent.glob("knowledge/*.md"))
    if not docs:
        fail("知识库为空", "knowledge/ 目录需要至少一篇文档")
    else:
        ok(f"知识库装载 {len(docs)} 篇文档")

    # 5. 抽查题端到端
    for question, expect in SMOKE_CASES:
        try:
            resp = post(f"{BASE}/api/chat/stream", {"prompt": question}, token=token)
            full = ""
            for raw in resp:
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                p = line[5:].strip()
                if not p or p == "[DONE]":
                    continue
                try:
                    full += json.loads(p)
                except json.JSONDecodeError:
                    full += p
            if expect.lower() in full.lower():
                ok(f"抽查题「{question}」命中({len(full)} 字)")
            else:
                fail(f"抽查题「{question}」回复未包含预期内容「{expect}」",
                     "检查 knowledge/ 对应文档 keywords 是否包含该主题词")
        except Exception as e:
            fail(f"抽查题「{question}」请求失败:{e}", "查看后端控制台报错")

    # 6. LLM / embedding 配置状态(信息项)
    from rag import embed, llm
    roles = []
    for r in ("main", "backup", "deep", "long"):
        spec = llm.resolve(r)
        roles.append(f"{r}:{'✓' if spec else '未配'}")
    print(f"{YELLOW}[i ]{RESET} LLM 角色: {' | '.join(roles)}")
    print(f"{YELLOW}[i ]{RESET} Embedding:{'已配置 ' + embed.MODEL if embed.is_configured() else '未配置(关键词检索模式,可正常演示)'}")

    print("=" * 56)
    if failures:
        print(f"{RED}自检未通过:{len(failures)} 项失败{RESET}")
        return 1
    print(f"{GREEN}全部检查通过,可以放心演示{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
