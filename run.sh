#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
python3 -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
