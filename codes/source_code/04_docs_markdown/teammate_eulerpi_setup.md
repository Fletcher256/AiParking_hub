# 队友电脑配置海鸥派环境方案

目标：让队友的 Windows 电脑具备和当前电脑类似的海鸥派开发/调试能力，能安全地做摄像头、Foxglove、录制、日志采集和后续感知开发。默认不启动 MCU bridge、CAN、serial actuator、电机、转向、刹车、油门。

## 推荐交付方式

最省时间、最稳定的方式是复制三件东西：

1. 本仓库 `D:\parking_board_agent`
2. 已经配置好的 Ubuntu VM 镜像
3. Windows 侧常用工具和驱动

不要让每台队友电脑从零手工搭 ROS2、交叉编译工具链、MPP SDK、Foxglove bridge。那些环境变量和版本组合很容易漂移。把 VM 当作标准开发环境复制，Windows 只负责控制、SSH、预览和文件中转。

## 队友电脑最低要求

- Windows 10/11
- Python 3.10 或更高
- 能运行 PowerShell
- 能和海鸥派处于同一网络：网线直连、同一 Wi-Fi、或同一个手机热点
- 如果要烧录 STM32：安装 ST-LINK 驱动
- 如果要看 UART 串口：安装 CH340/CH341、CP210 或 FTDI 驱动，并使用真实 USB-UART 连接
- Foxglove Studio 或浏览器端 Foxglove
- VLC 或 PotPlayer，用于直接看 RTSP

## 一键预检

在队友电脑上打开 PowerShell：

```powershell
cd D:\parking_board_agent
.\tools\windows_teammate_preflight.ps1
```

如果没有 `.venv`，先创建并安装 Windows 控制侧依赖：

```powershell
cd D:\parking_board_agent
.\tools\windows_teammate_preflight.ps1 -CreateVenv -InstallPythonDeps
```

如果队友的板端或 VM IP 不同：

```powershell
.\tools\windows_teammate_preflight.ps1 -BoardHost 172.20.10.2 -VmHost 192.168.247.129
```

预检结果会写入：

```text
D:\parking_board_agent\artifacts\teammate_preflight
```

## 标准网络变量

当前这台电脑的常用配置是：

```powershell
$env:BOARD_HOST="172.20.10.2"
$env:VM_SSH_HOST="192.168.247.129"
$env:VM_SSH_USER="ebaina"
$env:VM_SSH_PASSWORD="ebaina"
```

队友电脑如果 IP 不同，不要直接改脚本源码，优先用环境变量或命令行参数覆盖。

## 安全验证命令

板端 SSH 只读验证：

```powershell
.\.venv\Scripts\python tools\board_run.py --host $env:BOARD_HOST "hostname; whoami; date"
```

VM SSH 只读验证：

```powershell
.\.venv\Scripts\python tools\vm_ssh_run.py --host $env:VM_SSH_HOST run "hostname; whoami; date"
```

这两个命令不启动相机、不启动 dToF、不启动 STM32、不启动车辆控制。

## 摄像头和 Foxglove 验证

优先使用当前已经验证过的 Wi-Fi/热点链路。

启动低带宽预览/Foxglove 相关感知链路前，确认车辆不会运动，并且不启用 STM32 控制路径。摄像头预览工具默认是感知侧，不启动底盘控制：

```powershell
.\.venv\Scripts\python tools\wifi_live_preview_control.py start --board-host 172.20.10.2 --vm-host 192.168.247.129
```

状态检查：

```powershell
.\.venv\Scripts\python tools\wifi_live_preview_control.py status --vm-host 192.168.247.129
```

停止：

```powershell
.\.venv\Scripts\python tools\wifi_live_preview_control.py stop --vm-host 192.168.247.129
```

Foxglove WebSocket 常用地址：

```text
ws://192.168.247.129:8766
ws://192.168.247.129:8765
```

如果队友电脑的 VM IP 不同，把地址里的 IP 换成预检脚本输出的 VM IP。

## VM 复制建议

把当前可用 VM 关机后导出或复制给队友，要求队友导入后确认：

- 用户名/密码：`ebaina` / `ebaina`
- ROS2 Humble 可用
- `~/parking_ws` 或当前 ROS 工作空间可用
- `ffmpeg`、OpenCV、Foxglove bridge 相关工具可用
- 能 SSH 登录

导入 VM 后，队友需要确认 VM IP：

```powershell
.\tools\windows_teammate_preflight.ps1 -SkipNetworkProbes
```

然后在 VM 里或 VMware 网络设置里确认实际 IP，再用：

```powershell
.\tools\windows_teammate_preflight.ps1 -VmHost <队友VM实际IP>
```

## 驱动判断

预检脚本会列出当前 Windows 可见的 USB 设备。

常见情况：

- `USB-SERIAL CH340` 在线：说明 USB-UART 串口可用，可能会出现 `COMx`
- `STM32 STLink` Code 28：说明 ST-LINK 驱动缺失，需要安装 ST 官方 `STSW-LINK009`
- 只有蓝牙 COM 口：说明没有真实 USB-UART 在线
- ST-LINK 在线不等于有 UART 串口；它可能只用于烧录/调试

## 交付清单

给队友时至少包含：

- `D:\parking_board_agent` 仓库完整目录
- Ubuntu VM 镜像或导出文件
- 海鸥派账号：`root` / `ebaina`
- VM 账号：`ebaina` / `ebaina`
- 当前可用板端 IP、VM IP
- ST-LINK 官方驱动下载说明
- CH341SER 驱动：卖家资料里有 `04. 开发工具\CH341SER.EXE`
- Foxglove 连接地址

## 不要让队友直接做的事

- 不要直接运行 MCU bridge、CAN actuator、serial actuator
- 不要发电机、转向、刹车、油门控制命令
- 不要在未确认 IP 和目标设备前执行 `rm`、`mv`、`ip`、`systemctl`、`reboot` 等命令
- 不要把 dToF 调试旧路径和当前摄像头路径混在一起

当前阶段推荐目标是：队友电脑先能 SSH 到板端和 VM，再能看到摄像头/Foxglove，最后再接入 STM32 只读状态监控。
