# 新电脑 Codex 对接提示词与环境配置文档

用途：在另一台 Windows 电脑上打开新的 Codex 对话时，直接把本文件中的“对接提示词”复制给 Codex，让它按本项目规则继续协助配置和验证环境。

## 对接提示词

请复制下面整段到新电脑上的 Codex 新对话：

```text
你正在协助配置 D:\parking_board_agent 项目环境。请先阅读并严格遵守仓库根目录 AGENTS.md。

当前项目是 Windows 主控 + 海鸥派 Euler Pi / SS928 板端 + Ubuntu VM 的自动泊车/感知调试环境。

目标：
1. 在这台新 Windows 电脑上完成项目环境预检。
2. 建立 Python 虚拟环境并安装 Windows 控制侧依赖。
3. 验证能访问 Ubuntu VM。
4. 验证能通过串口访问海鸥派板端。
5. 只做安全的只读验证，不启动任何车辆、MCU、CAN、串口执行器、电机、转向、刹车、油门相关控制。

工作目录：
D:\parking_board_agent

必须遵守的安全规则：
- 板端通过 COM11，115200 baud，工具是 tools\board_serial.py。
- 板端登录 root / ebaina。
- Ubuntu VM 默认 SSH 是 192.168.137.100:22，用户 ebaina，密码 ebaina，工具是 tools\vm_ssh_run.py。
- 如果 COM11 打不开，不要猜测，先提示我关闭 MobaXterm 或其他占用 COM11 的串口软件。
- 只读命令可以直接跑，例如 whoami、hostname、date、df -h。
- 重要或危险命令必须先展示完整命令、说明目的、说明风险，并等我明确批准后，才允许带 --allow-risk 执行。
- 禁止直接启动 MCU bridge、CAN actuator、serial actuator、motor、steering、brake、throttle 或任何车辆控制命令。
- systemctl、reboot、rm、mv、chmod、chown、ip、iptables、docker、mount、umount、fdisk、parted、mkfs、dd、resize2fs、growpart、包安装等都必须先审批。

请按以下顺序执行：

1. 检查仓库是否存在：
   cd D:\parking_board_agent
   dir

2. 检查 Python：
   py -3 --version
   如果 py 不存在，再试：
   python --version

3. 如果 .venv 不存在，创建虚拟环境：
   py -3 -m venv .venv

4. 安装 Windows 侧依赖：
   .\.venv\Scripts\python -m pip install -r requirements-windows.txt

5. 跑项目预检：
   .\tools\windows_teammate_preflight.ps1

6. 如果需要一键创建虚拟环境和安装依赖，可用：
   .\tools\windows_teammate_preflight.ps1 -CreateVenv -InstallPythonDeps

7. 验证 VM SSH，只读：
   .\.venv\Scripts\python tools\vm_ssh_run.py --host 192.168.137.100 --user ebaina --password ebaina run "whoami"

8. 验证海鸥派串口，只读：
   .\.venv\Scripts\python tools\board_serial.py --login-password "ebaina" run "whoami"

9. 把预检结果和失败项整理给我，尤其是：
   - Python 是否可用
   - .venv 是否可用
   - paramiko / pyserial / numpy 是否安装成功
   - Windows 能看到哪些 COM 口
   - COM11 是否可打开
   - VM SSH 是否可达
   - 板端串口是否可登录
   - 是否发现驱动缺失，例如 CH340/CH341、ST-LINK

当前阶段不要启动感知链路、不要启动 dToF/camera sample、不要启动 ROS launch、不要启动 STM32 bridge。先完成只读连通性检查。
```

## 新电脑人工准备清单

在打开 Codex 前，先确认：

- Windows 10/11 可用。
- 已复制完整项目目录到 `D:\parking_board_agent`。
- 已安装 Python 3.10 或更高版本。
- 已安装 Git，必要时安装 Git LFS。
- 已安装串口驱动：CH340/CH341，必要时 CP210/FTDI。
- 如果要烧录 STM32，安装 ST-LINK 驱动。
- 已准备 Ubuntu VM，默认账户 `ebaina` / `ebaina`。
- 新电脑、Ubuntu VM、海鸥派板端处在可互通网络。
- 如果使用串口，MobaXterm、串口助手、Keil 等没有占用 COM11。

## 常用命令

进入项目：

```powershell
cd D:\parking_board_agent
```

创建虚拟环境：

```powershell
py -3 -m venv .venv
```

安装依赖：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-windows.txt
```

预检：

```powershell
.\tools\windows_teammate_preflight.ps1
```

一键预检并尝试创建环境：

```powershell
.\tools\windows_teammate_preflight.ps1 -CreateVenv -InstallPythonDeps
```

验证 VM：

```powershell
.\.venv\Scripts\python tools\vm_ssh_run.py --host 192.168.137.100 --user ebaina --password ebaina run "whoami"
```

验证海鸥派串口：

```powershell
.\.venv\Scripts\python tools\board_serial.py --login-password "ebaina" run "whoami"
```

如果板端 IP 或 VM IP 不是默认值，临时覆盖：

```powershell
$env:VM_SSH_HOST="192.168.137.100"
$env:VM_SSH_USER="ebaina"
$env:VM_SSH_PASSWORD="ebaina"
$env:BOARD_SERIAL_PORT="COM11"
$env:BOARD_SERIAL_BAUD="115200"
```

## 预检结果位置

预检日志和 JSON 会写入：

```text
D:\parking_board_agent\artifacts\teammate_preflight
```

把最新的 `preflight_*.log` 或 `preflight_*.json` 发回来，就能继续判断缺什么。

## 常见问题

### COM11 打不开

通常是 MobaXterm、串口助手、Keil、另一个 Python 进程占用了串口。关闭这些程序后再试。

也可能是新电脑上的端口号不是 COM11。到设备管理器查看实际 COM 号，然后设置：

```powershell
$env:BOARD_SERIAL_PORT="COMx"
```

### VM SSH 不通

先确认 VM 已启动，并在 VM 内查看 IP。新电脑上再用实际 IP 覆盖：

```powershell
$env:VM_SSH_HOST="<实际VM IP>"
```

然后重新跑：

```powershell
.\tools\windows_teammate_preflight.ps1 -VmHost <实际VM IP>
```

### Python 不存在

安装 Python 3.10+，并勾选 `Add python.exe to PATH`。安装后重新打开 PowerShell。

### 依赖安装失败

优先确认 `.venv` 可用：

```powershell
.\.venv\Scripts\python --version
```

然后升级 pip：

```powershell
.\.venv\Scripts\python -m pip install --upgrade pip
```

再安装：

```powershell
.\.venv\Scripts\python -m pip install -r requirements-windows.txt
```

## 当前阶段不要做的事

- 不要启动 `perception_link_manager.py adapt`。
- 不要启动 dToF/camera sample。
- 不要启动 ROS launch。
- 不要启动 STM32 bridge。
- 不要发送任何运动、舵机、电机、刹车、油门命令。
- 不要修改网络、防火墙、路由、系统服务，除非已经按审批流程明确批准。

## 后续推进顺序

只读连通性完成后，再按实际目标推进：

1. Windows 到 VM SSH。
2. Windows 到海鸥派串口。
3. Windows/VM 网络互通。
4. 只读查看摄像头或 Foxglove。
5. dToF/camera 官方链路验证。
6. ROS 感知链路。
7. 自动泊车 dry-run。
8. 经过审批后才进入任何车体控制相关测试。

