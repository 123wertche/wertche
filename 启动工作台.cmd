@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 缺少项目 Python：.venv\Scripts\python.exe
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "preflight_douyin.py" --json
if errorlevel 1 (
  echo 环境或授权预检未通过。请先运行 初始化项目.cmd 并按提示修复。
  pause
  exit /b 1
)
".venv\Scripts\python.exe" "start_workbench.py"
if errorlevel 1 pause
