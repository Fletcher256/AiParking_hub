@echo off
setlocal
cd /d "%~dp0\.."
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 60 --allow-risk "/opt/parking/stm32_uart/stm32_v2_safe_query.sh"
