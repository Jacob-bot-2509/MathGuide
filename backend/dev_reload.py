"""开发期热重载守护:backend 下 *.py 一变,强杀重启 uvicorn(默认 8000)。

为什么不用 uvicorn 自带的 --reload:
它的重启协议在 Windows 上是 os.kill(worker, CTRL_C_EVENT) 通知旧进程退出,
而 CTRL_C_EVENT 是传统 conhost 的控制台事件广播 —— 这台机器的默认终端是
Windows Terminal(ConPTY),广播投递失效,旧 worker 收不到信号永不退出,
reloader 卡死在等它退出的 join() 上(实测:强杀旧 worker 后 reloader 立刻恢复,
卡点即在此;把检测层换成 watchfiles 无效,因为 restart 协议是同一个)。
本守护直接用 terminate 强杀,此路径实测可靠;
被强杀掐断的回答由前端「回答已中断」标记兜底(SSE 收尾契约,见 README)。

用法:python dev_reload.py [端口]
- 改 backend 下的 .py,自动强杀重启(embedding 预热随新进程自动跑);
- 窗口里按 Ctrl+C 退出,会带走 uvicorn,不残留;
- 直接把窗口点 X 关闭会留下孤儿 uvicorn(Windows 不杀子进程树),
  下次启动本守护时会先清掉占着端口的残留。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from watchfiles import DefaultFilter, watch

PORT = sys.argv[1] if len(sys.argv) > 1 else "8000"
ROOT = Path(__file__).resolve().parent

proc: subprocess.Popen | None = None


def free_port(port: str) -> None:
    """杀掉占着目标端口的残留 uvicorn(上次窗口被直接点 X 留下的孤儿)。
    只对 python 进程下手,避免误杀无关程序。"""
    out = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, check=False
    ).stdout
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        # 形如:TCP 127.0.0.1:8000 0.0.0.0:0 LISTENING 21800
        if len(parts) >= 4 and f":{port}" in parts[1] and "LISTENING" in parts:
            pids.add(parts[-1])
    for pid in pids:
        name = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, check=False,
        ).stdout
        if "python" in name.lower():
            subprocess.run(["taskkill", "/F", "/PID", pid],
                           capture_output=True, check=False)
            print(f"[dev_reload] 清掉残留进程 PID {pid}(端口 {port})")


def start() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app",
         "--host", "127.0.0.1", "--port", PORT],
        cwd=ROOT,
    )


def restart() -> None:
    global proc
    if proc is not None and proc.poll() is None:
        proc.kill()  # 强杀,不走 Ctrl+C 控制台广播(那在 ConPTY 下失效)
        proc.wait()
    proc = start()
    print(f"[dev_reload] 已重启 uvicorn(端口 {PORT})")


def main() -> None:
    global proc
    free_port(PORT)
    proc = start()
    try:
        # DefaultFilter 已排除 __pycache__/.git 等目录;再筛一道,只认 .py。
        # yield_on_timeout 让 watch 定期空转,顺带监视 uvicorn 意外退出
        # (如端口被占绑定失败、代码 fatal error),退出就自动重起
        for changes in watch(ROOT, watch_filter=DefaultFilter(),
                             yield_on_timeout=True):
            changed = [p for _, p in changes if p.endswith(".py")]
            if changed:
                print(f"[dev_reload] 检测到变更: {', '.join(changed)}")
                restart()
            elif proc is not None and proc.poll() is not None:
                print("[dev_reload] uvicorn 意外退出,自动重起")
                proc = start()
    except KeyboardInterrupt:
        pass
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
        print("[dev_reload] 已退出")


if __name__ == "__main__":
    main()
