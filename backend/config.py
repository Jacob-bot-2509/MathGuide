"""
本地配置加载:backend/.env.local(已被 .gitignore 排除,key 永不入库)。

用法:复制 .env.local.example → .env.local,填入真实 API Key。
main.py 启动时最先调用 load_env(),之后各模块经 os.getenv 读取。
"""
import os
from pathlib import Path

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
