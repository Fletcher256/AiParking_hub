@echo off
setlocal
cd /d "%~dp0\.."
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 30 "echo STATUS_BEGIN; cat /tmp/parking_stm32_uart_boot_status.json 2>/dev/null; echo STATUS_END; echo LOG_TAIL_BEGIN; tail -80 /tmp/parking_stm32_uart_boot.log 2>/dev/null; echo LOG_TAIL_END"
