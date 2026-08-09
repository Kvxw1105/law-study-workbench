@echo off
setlocal
cd /d %~dp0

rem 薄壳：全部逻辑在 scripts\alpha_launcher.py（可测试）
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python。
  echo 请安装 Python 3.11 或更高版本，并在安装时勾选 Add Python to PATH。
  pause
  exit /b 1
)

python scripts\alpha_launcher.py
set "RC=%errorlevel%"
if not "%RC%"=="0" (
  echo.
  echo 启动失败（退出码 %RC%）。详见上方日志，或查看 logs\launcher.log
  pause
)
exit /b %RC%
