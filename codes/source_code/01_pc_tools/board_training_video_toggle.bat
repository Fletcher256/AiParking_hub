@echo off
cd /d "%~dp0\.."
.venv\Scripts\python tools\board_training_video_toggle.py %*
