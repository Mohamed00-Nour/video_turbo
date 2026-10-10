@echo off
cd /d "%~dp0"
python video_studio.py
if errorlevel 1 pause
