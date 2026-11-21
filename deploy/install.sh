#!/usr/bin/env bash
# MathGuide 网页版服务器安装脚本（在解压后的项目根目录执行）
# 用法: bash deploy/install.sh
set -euo pipefail

APP_DIR="${APP_DIR:-$(pwd)}"
PYTHON="${PYTHON:-python3}"

cd "$APP_DIR"

echo "== MathGuide install: $APP_DIR =="
if ! "$PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "需要 Python 3.11+；当前: $("$PYTHON" --version 2>&1)" >&2
  exit 1
fi

if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt

mkdir -p backend/data
chmod 700 backend/data || true

if [ ! -f backend/.env.local ]; then
  cp deploy/env.production.example backend/.env.local
  chmod 600 backend/.env.local
  echo "已生成 backend/.env.local；请填入真实 Key 后再启动。"
fi

echo
echo "检查无头浏览器（PDF 导出需要）:"
for bin in chromium chromium-browser google-chrome microsoft-edge; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "  found: $bin -> $(command -v "$bin")"
    break
  fi
done
if ! command -v chromium >/dev/null 2>&1 \
   && ! command -v chromium-browser >/dev/null 2>&1 \
   && ! command -v google-chrome >/dev/null 2>&1 \
   && ! command -v microsoft-edge >/dev/null 2>&1; then
  echo "  WARN: 未找到 Chromium/Chrome/Edge；文档 PDF 导出会失败。"
fi

echo
echo "安装完成。下一步:"
echo "  1. 编辑 backend/.env.local，填入模型 Key 与生产配置"
echo "  2. 将题库/数据放入 backend/data（需要时）"
echo "  3. sudo cp deploy/mathguide.service /etc/systemd/system/"
echo "  4. sudo systemctl daemon-reload && sudo systemctl enable --now mathguide"
echo "  5. 配置 deploy/Caddyfile 或 deploy/nginx.conf 并启动反代"
