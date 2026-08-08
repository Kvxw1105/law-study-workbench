@echo off
setlocal
cd /d %~dp0
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python 3.11 或更高版本。
  echo 请先安装 Python，并在安装时勾选 Add Python to PATH。
  pause
  exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo [1/3] 创建本地运行环境...
  python -m venv .venv
  if errorlevel 1 goto :failed
  echo [2/3] 安装依赖...
  .venv\Scripts\python -m pip install -r requirements.txt
  if errorlevel 1 goto :failed
)
echo [3/3] 启动法学语义学习工作台...
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8765"
.venv\Scripts\python -m uvicorn app.asgi:app --host 127.0.0.1 --port 8765
goto :end
:failed
echo [错误] 初始化失败，请查看上方日志。
pause
exit /b 1
:end
endlocal
