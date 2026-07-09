@echo off
cd /d "%~dp0\.."
.venv\Scripts\python tools\board_yolo_training_pipeline.py %*
