@echo off
setlocal
cd /d %~dp0

rem Alpha 自检。默认 --quick（秒级）；可传 --full 运行完整验证。
rem 用法：双击本文件，或运行 ALPHA_CHECK_WINDOWS.bat --full
set "MODE=%1"
if "%MODE%"=="" set "MODE=--quick"

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python。
  pause
  exit /b 1
)

echo ============================================================
echo  law-study-workbench  Alpha Doctor  (python scripts\alpha_doctor.py %MODE%)
echo ============================================================
python scripts\alpha_doctor.py %MODE%
set "RC=%errorlevel%"
echo.
echo 退出码 %RC%（0=全 PASS，1=有 FAIL，2=有 BLOCKED）
pause
exit /b %RC%
