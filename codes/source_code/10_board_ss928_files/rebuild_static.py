"""Rebuild sample_os08a20_dtof with -static on VM, then deploy to board."""
import paramiko, time, sys

HOST_VM = '192.168.247.129'; USER_VM = 'ebaina'; PASS_VM = 'ebaina'
HOST_BOARD = '192.168.137.2'; USER_BOARD = 'root'; PASS_BOARD = 'ebaina'
BUILD = '/home/ebaina/os08a20_dtof_build'
BINARY = 'sample_os08a20_dtof'
DEST_DIR = '/opt/sample/mipi_rgb_dtof_demo'
SSH_OPTS = '-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST_VM, username=USER_VM, password=PASS_VM, timeout=10)

def run_vm(cmd, timeout=60):
    _, out, err = c.exec_command(cmd, timeout=timeout)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode(), err.read().decode()

# 1. Check if static libpthread.a and libdl.a exist in the cross-toolchain
rc, o, _ = run_vm("ls /usr/aarch64-linux-gnu/lib/libpthread.a /usr/aarch64-linux-gnu/lib/libdl.a 2>&1")
print("Static libs:", o.strip())

# 2. Update Makefile to add -static to link step
new_makefile = r"""CC      = aarch64-linux-gnu-gcc

CFLAGS  = -Dss928v100 -DOT_XXXX -DISP_V2 -Wall \
          -fsigned-char -march=armv8-a -fPIE -pie \
          -DUSER_BIT_64 -DKERNEL_BIT_64 \
          -DSENSOR0_TYPE=OV_OS08A20_MIPI_8M_30FPS_12BIT \
          -DSENSOR1_TYPE=HISI_GS1860_MIPI_1M_30FPS_10BIT \
          -DOT_ACODEC_TYPE_HDMI -DOT_ACODEC_TYPE_INNER

INC     = -I./sdk/include/hisilicon \
          -I./sdk/include/hisilicon/exp_inc \
          -I./sdk/include/hisilicon/osal/include \
          -I./sdk/include/3rdparty \
          -I./sdk/common \
          -I./scene_auto/include \
          -I./scene_auto/src/sample \
          -I./scene_auto/tools/configaccess/include \
          -I./scene_auto/tools/iniparser/include \
          -I./dtof/include

SRCS    = os08a20_dtof.c \
          dtof_dumpraw.c \
          pwm.c \
          scene_auto/tools/configaccess/src/ot_confaccess.c \
          scene_auto/tools/iniparser/src/dictionary.c \
          scene_auto/tools/iniparser/src/iniparser.c \
          scene_auto/src/core/ot_scene.c \
          scene_auto/src/core/ot_scene_setparam.c \
          scene_auto/src/core/scene_setparam_inner.c \
          scene_auto/src/sample/scene_loadparam.c \
          sdk/common/sample_comm_sys.c \
          sdk/common/sample_comm_isp.c \
          sdk/common/sample_comm_vi.c \
          sdk/common/sample_comm_vo.c \
          sdk/common/sample_comm_vpss.c \
          sdk/common/sample_comm_venc.c \
          sdk/common/sample_comm_region.c \
          sdk/common/loadbmp.c

OBJS    = $(SRCS:.c=.o)

SDK_LIBS  = $(wildcard sdk/lib/*.a)
DTOF_LIBS = dtof/lib/libdepth_process.a dtof/lib/libsns_gs1860.a

TARGET  = sample_os08a20_dtof

.PHONY: all clean

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) $(INC) -o $@ $^ \
		-Wl,--start-group $(SDK_LIBS) $(DTOF_LIBS) -Wl,--end-group \
		-static -lpthread -lm -ldl -lstdc++ -lgcc -lgcc_eh

%.o: %.c
	$(CC) $(CFLAGS) $(INC) -c $< -o $@

clean:
	rm -f $(TARGET) $(OBJS)
"""

# Write Makefile via echo (using heredoc on VM)
rc, o, e = run_vm(f"cat > {BUILD}/Makefile << 'MAKEFILEEOF'\n{new_makefile}\nMAKEFILEEOF")
print(f"Write Makefile: rc={rc}", e.strip() if e.strip() else "ok")

# 3. Clean and rebuild
print("\n=== Building (static) ===")
rc, o, e = run_vm(f"cd {BUILD} && make clean && make 2>&1", timeout=120)
print(o[-3000:] if len(o) > 3000 else o)
if e.strip():
    print("STDERR:", e[-2000:])
print(f"rc={rc}")

if rc != 0:
    print("Build FAILED")
    c.close()
    sys.exit(1)

# 4. Check binary
rc, o, _ = run_vm(f"ls -lh {BUILD}/{BINARY} && strings {BUILD}/{BINARY} | grep 'GLIBC_' | sort -u")
print("\nBinary info + GLIBC deps:")
print(o.strip())

# 5. Deploy to board
print("\n=== Deploying to board ===")
rc, o, e = run_vm(f'sshpass -p {PASS_BOARD} scp {SSH_OPTS} {BUILD}/{BINARY} {USER_BOARD}@{HOST_BOARD}:{DEST_DIR}/{BINARY}', timeout=30)
print(f"SCP: rc={rc}", e.strip() if e.strip() else "ok")

# 6. Verify on board
rc, o, _ = run_vm(f'sshpass -p {PASS_BOARD} ssh {SSH_OPTS} {USER_BOARD}@{HOST_BOARD} "ls -lh {DEST_DIR}/{BINARY}"')
print("Board:", o.strip())

c.close()
print("Done.")
