#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 Python 3.11 或更高版本。" >&2
  exit 1
fi
if [ ! -x .venv/bin/python ]; then
  echo "[1/3] 创建本地运行环境..."
  python3 -m venv .venv
  echo "[2/3] 安装依赖..."
  .venv/bin/python -m pip install -r requirements.txt
fi
echo "[3/3] 启动法学语义学习工作台..."
(
  sleep 2
  .venv/bin/python -m webbrowser http://127.0.0.1:8765 >/dev/null 2>&1 || true
) &
exec .venv/bin/python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
