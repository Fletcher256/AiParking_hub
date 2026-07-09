@echo off
cd /d "%~dp0\.."
.venv\Scripts\python tools\training_capture_toggle.py toggle
pause
