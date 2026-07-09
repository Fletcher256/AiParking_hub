import paramiko

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2'; USER_BOARD = 'root'; PASS_BOARD = 'ebaina'
BUILD = '/home/ebaina/os08a20_dtof_build'
BINARY = 'sample_os08a20_dtof'
DEST_DIR = '/opt/sample/mipi_rgb_dtof_demo'

SSH_OPTS = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run(cmd, timeout=30):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# Ensure destination directory exists on board
rc, o, e = run(f'sshpass -p {PASS_BOARD} ssh {SSH_OPTS} {USER_BOARD}@{HOST_BOARD} "mkdir -p {DEST_DIR}"')
print(f'mkdir: rc={rc}', e.strip() if e.strip() else 'ok')

# SCP with explicit destination filename
src = f'{BUILD}/{BINARY}'
dst = f'{USER_BOARD}@{HOST_BOARD}:{DEST_DIR}/{BINARY}'
rc, o, e = run(f'sshpass -p {PASS_BOARD} scp {SSH_OPTS} {src} {dst}', timeout=30)
if rc == 0:
    print('SCP OK')
else:
    print(f'SCP FAILED rc={rc}:', e.strip())

# Verify
rc, o, _ = run(f'sshpass -p {PASS_BOARD} ssh {SSH_OPTS} {USER_BOARD}@{HOST_BOARD} "ls -lh {DEST_DIR}/{BINARY} && file {DEST_DIR}/{BINARY}"')
print('Board verify:', o.strip())

c.close()
