@echo off
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo 未检测到 Python 3.11 或更高版本。
  pause
  exit /b 1
)
python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
pause
