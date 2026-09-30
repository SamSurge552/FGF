@echo off
cd /d "%~dp0"
wscript //nologo "%~dp0launch.vbs" chat_gui.py
exit /b
