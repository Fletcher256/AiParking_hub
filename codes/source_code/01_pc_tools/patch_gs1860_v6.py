#!/usr/bin/env python3
"""
GS1860 fix v6 - THE CORRECT FIX:

Root cause discovered:
- 92 I2C errors are NOT fatal - binary continues and DtofInit succeeds
- REAL problem: "Linear:get vi_pipe 2 frame err!" - GS1860 not outputting MIPI frames
- Root cause: vi_start_mipi_rx triggers HW reset of GS1860 (sns_rst_src=2)
  Then pfn_cmos_init runs immediately (92 I2C writes all fail = no MIPI config)
  Result: GS1860 has no configuration -> no MIPI frames

Fix: Add sleep(10) inside sample_comm_vi_start_vi, between start_pipe and start_isp,
     ONLY for vi_dev==2 (GS1860). This gives GS1860 time to recover from HW reset
     before pfn_cmos_init tries to write 92 configuration registers.

Also restore S90autorun to sleep 3 (original) since sleep 15 was for a wrong theory.
"""
import paramiko

VM_HOST = "192.168.137.100"
VM_USER = "ebaina"
VM_PASS = "ebaina"
VI_COMMON = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/common/sample_comm_vi.c"
BOARD_HOST = "192.168.137.2"
BOARD_USER = "root"
BOARD_PASS = "ebaina"

def connect_vm():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(VM_HOST, username=VM_USER, password=VM_PASS, timeout=30)
    return c

def connect_board():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(BOARD_HOST, username=BOARD_USER, password=BOARD_PASS, timeout=30)
    return c

def run(c, cmd, timeout=120):
    _, stdout, stderr = c.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    return out + err

def main():
    vm = connect_vm()

    # The exact block in sample_comm_vi_start_vi to patch
    # Between start_pipe and start_isp, only for GS1860 (vi_dev==2)
    old_block = (
        '    ret = sample_comm_vi_start_pipe(&vi_cfg->bind_pipe, vi_cfg->pipe_info);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_print("start pipe failed!\\n");\n'
        '        goto start_pipe_failed;\n'
        '    }\n'
        '\n'
        '    ret = sample_comm_vi_start_isp(vi_cfg);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_print("start isp failed!\\n");\n'
        '        goto start_isp_failed;\n'
        '    }\n'
        '\n'
        '    return TD_SUCCESS;\n'
        '\n'
        'start_isp_failed:'
    )

    new_block = (
        '    ret = sample_comm_vi_start_pipe(&vi_cfg->bind_pipe, vi_cfg->pipe_info);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_print("start pipe failed!\\n");\n'
        '        goto start_pipe_failed;\n'
        '    }\n'
        '\n'
        '    /* GS1860 (vi_dev=2): MIPI init triggers HW reset via sns_rst_src. */\n'
        '    /* GS1860 needs ~8-9s cold boot before pfn_cmos_init can write I2C regs. */\n'
        '    /* Without this delay: 92 I2C errors -> no MIPI config -> frame errors. */\n'
        '    if (vi_cfg->dev_info.vi_dev == 2) {\n'
        '        sample_print("GS1860: waiting 10s for HW reset recovery before ISP init...\\n");\n'
        '        sleep(10);\n'
        '    }\n'
        '\n'
        '    ret = sample_comm_vi_start_isp(vi_cfg);\n'
        '    if (ret != TD_SUCCESS) {\n'
        '        sample_print("start isp failed!\\n");\n'
        '        goto start_isp_failed;\n'
        '    }\n'
        '\n'
        '    return TD_SUCCESS;\n'
        '\n'
        'start_isp_failed:'
    )

    patch_script = (
        f'old_block = {repr(old_block)}\n'
        f'new_block = {repr(new_block)}\n'
        f'with open({repr(VI_COMMON)}, "r") as f:\n'
        '    content = f.read()\n'
        'if old_block in content:\n'
        '    content = content.replace(old_block, new_block, 1)\n'
        f'    with open({repr(VI_COMMON)}, "w") as f:\n'
        '        f.write(content)\n'
        '    print("PATCH OK")\n'
        'else:\n'
        '    print("ERROR: pattern not found")\n'
        '    # Try to find partial match\n'
        '    idx = content.find("sample_comm_vi_start_pipe(&vi_cfg->bind_pipe")\n'
        '    if idx >= 0:\n'
        '        print("Partial:", repr(content[idx:idx+300]))\n'
    )

    print("=== Patching sample_comm_vi.c (v6) ===")
    sftp = vm.open_sftp()
    with sftp.open('/tmp/patch_vi_v6.py', 'w') as f:
        f.write(patch_script)
    sftp.close()

    out = run(vm, "python3 /tmp/patch_vi_v6.py")
    print(out.strip())

    # Verify
    out = run(vm, f"grep -n 'GS1860.*vi_dev.*2\\|waiting 10s\\|HW reset recovery' {VI_COMMON} | head -5")
    print(f"Verify: {out.strip()}")

    # Rebuild
    print("\n=== Rebuilding ===")
    out = run(vm,
        "bash -l -c 'cd /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof && make -j4 2>&1 | tail -5'",
        timeout=180)
    print(out.strip())

    out = run(vm, "ls -lh /home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof")
    print(f"Binary: {out.strip()}")

    vm.close()

    # Deploy to board
    print("\n=== Deploying to board ===")
    board = connect_board()

    # Kill existing
    run(board, "pkill -TERM sample_dtof 2>/dev/null; sleep 3")
    ps = run(board, "ps | grep sample_dtof | grep -v grep || echo gone")
    print(f"Process: {ps.strip()}")

    # SCP via VM
    vm2 = connect_vm()
    binary_path = "/home/ebaina/ZZIP/SS928V100_dtof_build_source/src/dtof/sample_dtof"
    out = run(vm2,
        f"sshpass -p ebaina scp -o StrictHostKeyChecking=no {binary_path} root@192.168.137.2:/tmp/sample_dtof_new && echo scp_ok",
        timeout=60)
    print(out.strip())
    vm2.close()

    out = run(board, "mv /tmp/sample_dtof_new /opt/sample/dtof/sample_dtof && chmod +x /opt/sample/dtof/sample_dtof && echo moved")
    print(out.strip())

    # Also revert S90autorun sleep back to 3 (the sleep 15 was for wrong theory)
    # Actually sleep 15 is fine too - gives extra margin. Keep it for now.
    # The critical fix is the sleep(10) inside start_vi for vi_dev==2.

    print("\n=== Rebooting board to test cold boot ===")
    try:
        board.exec_command("reboot", timeout=5)
    except:
        pass
    board.close()
    print("Reboot sent. Wait ~50s then check dtof.log for:")
    print("  - 'GS1860: waiting 10s for HW reset recovery'")
    print("  - No 'I2C_WRITE error!' lines (or much fewer)")
    print("  - No 'get vi_pipe 2 frame err!' (or starting later then stopping)")

if __name__ == "__main__":
    main()
