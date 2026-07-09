@echo off
setlocal
cd /d "%~dp0.."

echo.
echo Board YOLO training pipeline
echo Workspace: %CD%
echo.
echo 1. status
echo 2. start recording
echo 3. stop recording
echo 4. stop recording and process videos
echo 5. process existing board videos
echo.
set /p CHOICE=Choose action [1-5]: 

if "%CHOICE%"=="1" (
  .venv\Scripts\python tools\board_yolo_training_pipeline.py status
  goto done
)

if "%CHOICE%"=="2" (
  .venv\Scripts\python tools\board_yolo_training_pipeline.py start
  goto done
)

if "%CHOICE%"=="3" (
  .venv\Scripts\python tools\board_yolo_training_pipeline.py stop
  goto done
)

if "%CHOICE%"=="4" (
  set /p OUTNAME=Output folder name [default auto timestamp]: 
  if "%OUTNAME%"=="" (
    .venv\Scripts\python tools\board_yolo_training_pipeline.py stop-process
  ) else (
    .venv\Scripts\python tools\board_yolo_training_pipeline.py stop-process --output-name "%OUTNAME%"
  )
  goto done
)

if "%CHOICE%"=="5" (
  set /p OUTNAME=Output folder name [default auto timestamp]: 
  if "%OUTNAME%"=="" (
    .venv\Scripts\python tools\board_yolo_training_pipeline.py process
  ) else (
    .venv\Scripts\python tools\board_yolo_training_pipeline.py process --output-name "%OUTNAME%"
  )
  goto done
)

echo Invalid choice.

:done
echo.
pause
