@echo off
setlocal
cd /d %~dp0
set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python 3.11 或更高版本。
  echo 请先安装 Python，并在安装时勾选 Add Python to PATH。
  pause
  exit /b 1
)

rem 端口占用检查：已在运行则不重复启动（/c: 使整串作为正则，避免空格被当作 OR 分隔）
netstat -ano | findstr /r /c:":%PORT% .*LISTENING" >nul 2>nul
if not errorlevel 1 (
  echo [提示] 端口 %PORT% 已有服务在监听，工作台可能已在运行。
  echo 直接打开 %URL%
  start "" %URL%
  exit /b 0
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
start "" cmd /c "timeout /t 3 >nul & start %URL%"
.venv\Scripts\python -m uvicorn app.asgi:app --host 127.0.0.1 --port %PORT%
goto :end
:failed
echo [错误] 初始化失败，请查看上方日志。
pause
exit /b 1
:end
endlocal
