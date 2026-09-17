@echo off
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo 需要管理员权限才能点进以管理员运行的游戏窗口。
  powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'gui.py' -Verb RunAs -WorkingDirectory '%~dp0'"
  exit /b
)
python gui.py
