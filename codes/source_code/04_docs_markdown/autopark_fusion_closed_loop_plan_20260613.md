# 摄像头 + IMU + 里程计 + STM32 融合闭环设计与执行计划（Codex 执行版）- 2026-06-13

> 本文档定义自动泊车的**多传感器融合闭环控制逻辑**，并给出 Codex 可按部就班落实的任务序列。
> 它是 `docs/autopark_codex_execution_plan_20260612.md`（主计划）的配套底层文档：主计划负责"选哪个动作"，本文档负责"动作执行得准不准、execution 期间车在哪"。
> 主计划的安全门、能力阶梯、动作库约定全部继承，本文不重复。

---

## 0. 固件现状盘点（2026-06-13 源码核实，Codex 不要重复实现已有的东西）

| 能力 | 状态 | 位置 |
|---|---|---|
| 左右轮独立驱动 + 编码器 + 速度 PID | ✅ 已有 | `SS928_hub/HARDWARE/Motors.c` (`lSetSpeed/rSetSpeed`, TIM3/TIM4 编码器, `PID_Speed`) |
| Ackermann 差速配合舵机 | ✅ 已实现，**未实车验证** | `CarControl.c::ApplyAckermannSpeedScale`（StartArcDrive 内调用），`Motor_SetSpeedScale` |
| IMU 航向 | ❌ **故障（2026-06-13 C0 实测）**：静止 YAW 假旋转 ~80°/s，ZERO_YAW 无效，必须先过 F4 | BMI270，`STAT` 返回 `YAW=`，`GetReportedYaw()`；链路见 F4 背景 |
| 编码器里程计 (x, y, θ, distance) | ✅ 已有 | `Motors.h::Odometry_t`，`Odometry_Update`（θ 来自轮差分） |
| 周期遥测骨架 | ⚠️ 有但格式不可用 | `CarControl.c::PrintTelemetry`：裸 CSV 无前缀无序号，难与 STAT/DONE 混流解析 |
| DONE 附带末态数据 | ⚠️ 机制有、内容空 | `CarProtocol_FinishActiveMotionOk(extra)` 的 `extra` 当前传 `""` |
| 运动超时保护 | ✅ 已有 | `DISTANCE_TIMEOUT_MS / TURN_TIMEOUT_MS` |
| 底盘几何常数 | ⚠️ 占位值未实测 | `WHEEL_TRACK_CM=14.5`（注释"需实测标定"）、`ACKERMANN_WHEEL_BASE_CM=16.0`（注释"calibrate on the chassis"） |

串口硬约束：**9600 8N1 ≈ 960 字节/秒**。所有遥测设计必须在这个预算内做帧率/字段取舍。

---

## 1. 闭环总体架构（级联三环）

```text
┌────────────────────────── 板端 Python (board_parking_controller.py) ──────────────────────────┐
│                                                                                                │
│  [外环] 每动作一次 (~0.2 Hz)        [中环] 运动期间 10 Hz                                        │
│  动作重规划器 (主计划 §7)            位姿融合器 PoseFuser + 运动中安全监视                          │
│   读稳定视觉状态                      输入: TLM(IMU+里程计) 5Hz + YOLO 帧(若稳定)                  │
│   评分选动作 ──── 下发命令 ────────►  输出: 融合位姿 / 早停 STOP / 一致性 verdict                  │
│   ▲                                                          │                                 │
│   └────────── 动作结束: 视觉重锚定 + 预测vs实测对账 ◄──────────┘                                 │
└──────────────────────────────┬─────────────────────────────────────────────────────────────────┘
              /dev/ttyUSB0 9600│8N1  (命令↓: MOVE/ARC/STOP)  (遥测↑: ACK/TLM×N/DONE)
┌──────────────────────────────▼─────────────────────────────────────────────────────────────────┐
│  [内环] STM32 50~100 Hz (已全部存在, 仅加遥测输出)                                                │
│  轮速 PID ←编码器        Ackermann 差速缩放 ←舵角        航向保持 PID ←IMU(直行时)                 │
│  里程计积分(x,y,θ,d)     距离终止判定(D±2cm)             超时/CANCELED 保护                        │
└────────────────────────────────────────────────────────────────────────────────────────────────┘
        摄像头链路(不动): OS08A20 → YOLO seg → UDP 127.0.0.1:24580 → 板端控制器
```

各传感器的分工（互补滤波的依据）：

| 传感器 | 强项 | 弱项 | 闭环中的角色 |
|---|---|---|---|
| 视觉(YOLO) | 车位相对位姿的**绝对**测量，无漂移 | 低频；运动中可能模糊/不稳；车位出视野就没了 | **锚**：每动作首尾重置融合位姿 |
| IMU(BMI270 yaw) | 短时航向变化精准，不受打滑影响 | 长时漂移；只有航向没有位移 | 运动中 θ 的主来源 |
| 编码器里程计 | 位移量可靠（轮子不滑时） | 打滑失真；θ(轮差分)受蹭地污染 | 运动中位移 Δd 的主来源；θ 仅作交叉校验 |
| STM32 内环 | 实时性（PID/终止/超时） | 不知道车位在哪 | 把"一个短动作"执行准 |

**核心思想**：视觉负责"车位在哪"（绝对、低频），IMU+里程计负责"这 6cm 里我动了多少"（相对、高频），STM32 负责"把命令执行准"。三者在板端 PoseFuser 汇合，得到运动全程连续的槽坐标系位姿——这就把现在"走完 6cm 才知道结果"的开环段，变成"运动中每 100ms 知道自己在哪、能随时早停"的闭环段。

---

## 2. 坐标系与符号约定（先定死，再写代码）

### 2.1 槽坐标系 (slot frame)

- 原点：车位入口边中点；**+y 指向车位内部**；+x 沿入口边、与图像 x 同向。
- 车辆参考点：**后轴中点** P。
- 位姿：`(x_s, y_s, φ)`，φ = 车体倒车运动方向与 +y 的夹角（车尾正对车位入口时 φ=0）。
- 与现有视觉状态的换算：`x_s ≈ slot_lateral_cm`，`y_s ≈ -slot_y_dist_cm`（入口外为负），`φ ≈ slot_heading_err_deg`。

### 2.2 符号验证实验（C0，写代码前必须做，30 分钟）

历史教训：`+x_cm` 误标 forward 坑过一次。所有符号**用实验定，不靠猜**：

1. 车静止，`STAT` 读基准 YAW；手动把车顶视顺时针转 ~10°，再读 YAW → 记录 IMU 符号 `S_yaw`。
2. 手推车后退 ~10cm，读 `STAT` 的 X/Y/D 变化 → 记录里程计前后符号 `S_d` 与左右符号。
3. 车摆在车位左侧/右侧各一次，dry-run 读 `slot_lateral_cm` 符号 → 确认视觉横向符号。
4. 产出 `configs/chassis_signs.json`：

```json
{
  "schema": "chassis_signs.v1",
  "verified_date": "",
  "yaw_cw_positive": null,
  "odom_d_reverse_negative": null,
  "odom_x_right_positive": null,
  "vision_lateral_left_negative": null,
  "notes": "由 C0 实验填写, 任何字段为 null 时 PoseFuser 拒绝启动"
}
```

PoseFuser 启动时加载该文件，把所有内部计算归一到 §2.1 约定。

---

## 3. 接口规格（固件 ↔ 板端，9600 波特预算内）

### 3.1 新遥测行 TLM（固件任务 F2）

把现有 `PrintTelemetry()` 的裸 CSV 改为带前缀可解析行：

```text
TLM <n> YAW=<deg> X=<cm> Y=<cm> D=<cm> V=<cm/s> ANG=<deg>
```

- `<n>`：自增序号（uint8 回绕），板端用于丢帧统计。
- 长度预算：约 55~65 字节 ≤ 65 字节。**5 Hz** = 325 B/s，占串口 1/3，给 ACK/DONE/STOP 留足余量。
- 触发条件：仅在 `IsAutoMotionMode()` 为真（MOVE/ARC/TURN 执行中）且 `TELEM=1` 时输出；空闲时不刷屏。
- 开关命令：沿用现有 telemetry enable 机制（`CarProtocol_IsTelemetryEnabled()`），确认/补充 V2 命令 `TELEM=0/1`，默认 0（保证旧链路行为完全不变）。
- 频率实现：`CarApp.c` 现有 `EXCOUNT(TelemetryCnt,100)` 改为可调到 5Hz（先实测当前 tick 周期再定分频数，**不要假设 tick=10ms**）。

### 3.2 DONE 携带末态（固件任务 F3）

利用现成的 `extra` 参数，把空字符串换成末态摘要：

```text
DONE <seq> ARC X=<cm> Y=<cm> D=<cm> YAW=<deg>
```

板端凭这一行完成对账，省一次 STAT 往返。`STOP`/`CANCELED`/`TIMEOUT` 路径同样补末态。

### 3.3 串口纪律（板端遵守）

- `TELEM=1` 期间**禁止轮询 STAT**（避免 STM32 端 TX 拥塞；`DROP` 字段>0 即违规证据）。
- 运动中板端只收：`ACK` → `TLM`×N → `DONE`。
- 板端解析器按行首 token 分发：`ACK/DONE/TLM/STAT/PWM/ERR`，未知行进 raw 日志不丢弃。

---

## 4. 板端融合闭环逻辑（PoseFuser，纯标准库，可单测）

### 4.1 数据结构

```python
# board_parking_controller.py 内 "# ===== fusion core =====" 段, 纯函数风格
FusedPose = {
    "x_s_cm": 0.0, "y_s_cm": 0.0, "phi_deg": 0.0,
    "source": "vision_anchor|dead_reckon|blended",
    "anchor_age_ms": 0, "tlm_count": 0, "tlm_lost_ms": 0,
    "innovation": {"x_cm": 0.0, "y_cm": 0.0, "phi_deg": 0.0},
    "consistency": {"imu_vs_odom_yaw_deg": 0.0, "ok": True},
}
```

### 4.2 一个动作周期内的状态机

```text
IDLE
 └─(规划器选定动作)→ ANCHORING   : 取10稳定帧均值 → 锚定 (x_s,y_s,φ)=视觉值; 锁存车位线几何
 └─(下发命令+收到ACK)→ EXECUTING : 每条TLM做DR传播(4.3); 每帧稳定视觉做温和校正(4.4);
                                   每100ms跑运动中安全门(4.5); 触发即发STOP
 └─(收到DONE)→ SETTLING          : 等 settle-sec, 取10稳定帧均值
 └─→ RECONCILING                 : 三方对账(4.6), 写JSONL, 更新响应模型输入
 └─→ IDLE (把最终视觉值重新设为锚, DR累计误差清零)
```

### 4.3 DR 传播（每条 TLM）

```text
Δd  = S_d  * (D_k - D_(k-1))          # 有符号位移, cm
Δψ  = S_yaw* (YAW_k - YAW_(k-1))      # 航向增量, deg, 处理 ±180 回绕
φ   += Δψ
x_s += Δd * sin(rad(φ - Δψ/2))        # 中点角积分
y_s += Δd * cos(rad(φ - Δψ/2))
θ_odom_delta = 由 X/Y 反推的轮差分航向增量   # 仅用于一致性检查, 不进位姿
```

### 4.4 运动中视觉校正（保守混合）

运动中的 YOLO 帧可能模糊，只做**门限内小步混合**，不做硬重置：

```text
若帧满足: pose_quality > 0.85 且 该帧自身 stable
  innovation = vision_pose - fused_pose
  若 |innov.x|<5cm 且 |innov.phi|<6°:   fused = fused + 0.3 * innovation
  否则: 记录 innovation 异常计数(连续3次异常 → 运动结束后 verdict=inconsistent)
```

### 4.5 运动中安全门（中环新增，原有门全部保留）

| 门 | 条件 | 动作 |
|---|---|---|
| TLM 丢失 | `TELEM=1` 下 >1000ms 无 TLM | STOP |
| IMU/里程计航向劈叉 | 单动作内 `|Δψ_imu - Δψ_odom| > 8°`（打滑特征） | STOP, verdict=slip |
| 预测压线 | 用融合位姿+锚定时锁存的车位线几何，外推 `min_margin_px` 等效值 <40px | STOP（**早停，不等 6cm 走完**） |
| 位移超界 | `|累计Δd| > 命令D × 1.5 + 2cm` | STOP, verdict=overrun |
| 视觉 0.5s 丢失门 | 维持原样（approach/align 相位） | STOP |

### 4.6 三方对账（每动作结束，写进同一条 JSONL）

```json
{"event": "fusion_reconcile", "step": 1,
 "commanded": {"cmd": "ARC D=-6.0 STE=120 V=1"},
 "dr_delta":     {"x_cm": 0, "y_cm": 0, "phi_deg": 0, "d_cm": 0},
 "vision_delta": {"x_cm": 0, "y_cm": 0, "phi_deg": 0},
 "innovation_at_end": {"x_cm": 0, "y_cm": 0, "phi_deg": 0},
 "imu_vs_odom_yaw_deg": 0,
 "scale_check": {"commanded_d": -6.0, "odom_d": 0, "vision_d_est": 0},
 "verdict": "consistent|slip|scale_off|inconsistent"}
```

判定阈值（初值，C 系列标定后修正）：`consistent` = 末端 innovation |x|<2cm、|φ|<3°、且 scale 偏差<20%。

**这份对账数据同时就是主计划 §6 响应模型的标定样本**——融合闭环不是另起炉灶，它让每次标定探针额外产出 IMU/里程计证据，响应模型从"纯视觉差分"升级为"带物理过程量的差分"。

---

## 5. 标定任务（C 系列，实车，人在场，每项 ≤1 小时）

**C0 符号验证**（§2.2）— 一切代码合并前完成。产出 `configs/chassis_signs.json`。

**C1 底盘几何实测**：卷尺量后轮轮距、前后轴距，更新 `Motors.h` 的 `WHEEL_TRACK_CM` / `ACKERMANN_WHEEL_BASE_CM`，重编译烧录。验收：常数与实测差 <0.3cm。

**C2 舵角→曲率标定**（替代猜测 STE 映射，与主计划 §6 探针合并执行）：
对 STE ∈ {60, 75, 105, 120} 各执行一次 `ARC D=-6.0 V=1` 探针（沿用主计划 §6.4 模板 + `TELEM=1`）：

```text
R_eff(STE) = Δd_odom / Δψ_imu(rad)      # 等效转弯半径
```

产出 `configs/chassis_kinematics.json`：

```json
{"schema": "chassis_kinematics.v1",
 "wheel_track_cm": 0, "wheel_base_cm": 0,
 "steer_curvature": [
   {"ste": 60, "r_eff_cm": null, "n": 0},
   {"ste": 75, "r_eff_cm": null, "n": 0},
   {"ste": 105, "r_eff_cm": null, "n": 0},
   {"ste": 120, "r_eff_cm": null, "n": 0}],
 "distance_scale": {"commanded_to_odom": null, "odom_to_vision": null}}
```

验收：同一 STE 两次 R_eff 偏差 <15%；左右对称档（60/120, 75/105）的 |R_eff| 比值在 0.7~1.4 内（不对称本身是有效发现，记录即可）。
**附带验证 Ackermann 差速**：每档跑 `DIFF on/off` 各一次（若固件已默认启用则先架空确认左右轮速比 = (R∓W/2)/R），对比 Δψ_imu 和重复性——差速开启后 Δψ 应显著更大更稳。

**C3 距离尺度**：`MOVE D=-6 / D=-12` 各 2 次，三方对账拿 `commanded→odom→vision` 两级尺度系数，写入 C2 的 json。验收：系数标准差 <10%。

---

## 6. Codex 任务序列（按依赖排序，每个任务可独立验收）

> 固件任务在 `SS928_hub/`（Keil 工程，编译烧录由用户操作，Codex 只改源码并自查）；板端任务在 `tools/board_parking_controller.py` + 部署 `/opt/parking/autopark/`；PC 工具任务在 `tools/`。
> 纪律：固件改动必须保持 `TELEM=0` 时与现行为**逐字节一致**；板端改动必须保持不加新旗标时行为不变；每任务完成更新本文档对应条目。

**F2（P0，固件，半天）结构化遥测**
按 §3.1 改 `PrintTelemetry` + 频率分频 + 仅运动中输出。先写一个临时测试：上电后 `TELEM=1` → 手转轮子 → 确认 TLM 行格式与频率。验收：5Hz±20%，行长 ≤65B，`TELEM=0` 时无任何输出，DROP 不增长。

**F3（P0，固件，2 小时）DONE 携带末态**
按 §3.2 填充 `FinishActiveMotionOk/Err` 的 extra。验收：MOVE/ARC/超时/CANCELED 四条路径的 DONE/ERR 行都带 X/Y/D/YAW。

执行记录（2026-06-13）：

```text
F2/F3 source implemented, not yet flashed to STM32.

Changed:
  SS928_hub/Core/CarControl.c
  SS928_hub/Core/CarControl.h
  SS928_hub/Core/CarProtocol.c
  SS928_hub/HARDWARE/CarApp.c

F2:
  periodic telemetry now emits:
    TLM <n> YAW=<deg> X=<cm> Y=<cm> D=<cm> V=<cm/s> ANG=<deg>
  Telemetry divider changed from EXCOUNT(...,100) to EXCOUNT(...,200)
  for about 5Hz when SysTick is 1ms.
  Legacy RC_STAT still calls PrintLegacyTelemetry() and keeps the old bare CSV.

F3:
  active-motion DONE now appends terminal state:
    DONE <seq> <cmd> X=<cm> Y=<cm> D=<cm> YAW=<deg>
  active-motion ERR now appends terminal state:
    ERR <seq> CODE=<code> X=<cm> Y=<cm> D=<cm> YAW=<deg>
  Non-motion ReplyDone/ReplyErr paths are unchanged.

Build:
  powershell -ExecutionPolicy Bypass -File build_gcc/build.ps1
  passed
  FLASH used: 61228 B / 64 KB = 93.43%
  outputs:
    SS928_hub/build/gcc/SS928_hub.hex
    SS928_hub/build/gcc/SS928_hub.bin

Pending hardware validation after user flashes:
  TELEM=0 no periodic TLM
  TEL ON + MOVE/ARC produces 5Hz +/-20% TLM lines
  TLM line length <=65B in normal ranges
  MOVE/ARC/TIMEOUT/CANCELED terminal lines include X/Y/D/YAW
  DROP does not increase during TELEMETRY ON motion
```

Hardware validation update after flash (2026-06-13):

```text
Flashed with ST-LINK/OpenOCD:
  openocd -f interface/stlink.cfg -f target/stm32f1x.cfg \
    -c "program D:/parking_board_agent/SS928_hub/build/gcc/SS928_hub.hex verify reset exit"
  result: Verified OK

Non-motion checks:
  PING: pass
  VER: pass, FW=SS928-CTRL-2.0 BAUD=9600 PROTO=2
  STAT: pass, DROP=0
  TEL ON while IDLE: pass after gating fix, no idle TLM spam
  TEL OFF: pass

Motion check:
  Command:
    TEL ON
    MOVE D=-6.0 V=1
    TEL OFF
  Result:
    ACK received
    TLM lines: 11
    DONE includes terminal state:
      DONE 8211 MOVE X=0.0 Y=-4.1 D=4.1 YAW=59.0
    Post STAT:
      MODE=IDLE RUN=STANDBY SPD=0 ANG=90.0 YAW=-25.7 X=0.0 Y=-5.1 D=5.2 DROP=0

Acceptance:
  F2/F3 protocol format: pass
  TLM during motion: pass
  terminal X/Y/D/YAW fields: pass
  DROP under this short motion: pass
  IMU yaw quality: not accepted yet. YAW changed implausibly during a short
    straight reverse move, so C0 must verify IMU yaw sign, zeroing, and stability
    before PoseFuser trusts YAW.
```

**C0（P0，实车，0.5 小时）符号验证** → `configs/chassis_signs.json`（§2.2）。

执行记录（2026-06-13）：

```text
YAW validation failed before sign verification.

Reports:
  docs/autopark_c0_yaw_validation_20260613.md
  artifacts/autopark_baseline/c0_yaw_static_before_zero_20260613.json
  artifacts/autopark_baseline/c0_yaw_static_after_zero_20260613.json

Static before ZERO_YAW:
  YAW samples:
    -152.5, 57.8, -94.0, 112.6, -37.2, 171.0, 17.6, -135.8, 73.3, -73.3
  range: 323.5 deg

Static after ZERO_YAW:
  YAW samples:
    69.1, -81.8, 128.9, -23.6, -178.7, 30.0, -118.7, 91.5, -63.6, 146.1
  range: 324.8 deg

Same-session rapid STAT:
  YAW advanced about 21.4 deg per sample while static, roughly 80 deg/s false yaw rate.

Conclusion:
  Not a simple YAW offset problem.
  Do not trust STAT YAW for PoseFuser.
  Add BMI270 gyro diagnostics and fix gyro zero/axis/scale/dt before accepting C0.
```

**F4（P0，固件+实车，半天~1 天）IMU YAW 修复 —— 阻塞 C0/B2/C2，最高优先**

背景：2026-06-13 C0 实测静止 YAW 以 ~80°/s 假旋转（10 样本范围 323.5°，逐样本步进近似恒定），`ZERO_YAW` 无效；短直线倒车 YAW 跳变 59°。**这不是慢漂移（零偏漂移量级是几°/分钟），是链路硬故障。** YAW 链路全貌：

```text
BMI270_Get_Raw (I2C 12B burst, 失败时 early-return 不更新)
 -> 减软件零偏 gyro_zero_z (仅开机 SoftCalibrate_Z(200) 标一次, 3 次失败仅 WARN 后继续)
 -> PT1 滤波 (cast int16)
 -> BMI270_Get_AngleDt: yaw += GyroZ * scale * dt   (纯开环积分, 无任何运行时修正)
 -> KalmanFilter_Update(Kal_Yaw) 平滑 (q=0.5, 不解决漂移)
 -> GetReportedYaw() -> STAT/TLM
```

**关键回归线索（先查这个，再查硬件）**：YAW 在 **2026-06-10 曾被物理验证可用**——车身左转 90° → YAW +86°（≈1:1，左转=正），当时还完成过 ARC 段 YAW 23.3→7.7 的合理记录。故障是在 2026-06-13 烧录 F2/F3 新固件后首次观测到的。回归窗口内的源码改动：`CarControl.c/h`、`CarProtocol.c`、**`CarApp.c`**（`ServiceMpuTask` 的 `MpuTaskElapsedMs` 计时与任务调度正在此文件，F2 的遥测分频改动也在此文件）。**F4a 第 0 步：diff 当前源码与 2026-06-10 可用版本，重点核对 `ServiceMpuTask` 的调用路径、`MpuTaskElapsedMs` 的累加/清零、SysTick 中断里任务标志的改动**——"静止时恒定步进假旋转"与 dt 单位错/任务饿死后 elapsedMs 巨量累积的特征吻合。若 06-10 版本可回烧，先回烧确认 YAW 恢复，即可锁定回归而非硬件。

**F4a 诊断先行（禁止盲改）**：新增 V2 命令 `GDIAG`，静止时输出：

```text
GDIAG ID=0x24 RANGE=<gyr_range寄存器> SCALE=<bmi270_gyro_scale*1e6> DT=<bmi270_dt*1000>ms ZZ=<gyro_zero_z> TEMP=<degC> I2CERR=<累计读失败数>
GDIAG RAWPRE  z0..z9   # 连续10个去零偏前的原始 GyroZ LSB
GDIAG RAWPOST z0..z9   # 连续10个去零偏后的 GyroZ LSB
```

（`I2CERR` 需在 `BMI270_READ_REG_CONTINUE_STATUS` 失败路径加计数器。）判读表：

| GDIAG 观测 | 根因定位 | 对应修复 |
|---|---|---|
| RAWPRE 恒为 ±32767 附近 | 陀螺配置/INIT blob 加载失败、量程寄存器错 | 修初始化序列与量程 |
| RAWPRE 静止时大且近恒定（几百~几千 LSB） | 寄存器错位读 / 字节序 / 开机标定时车被动过 | 修读取或重标 |
| RAWPRE 正常小、RAWPOST 仍大 | `gyro_zero_z` 坏值（3 次标定失败走了 WARN 分支） | F4b-2/3/4 |
| `I2CERR` 持续增长 | **嫌疑最大**：`BMI270_Get_Raw` 失败 early-return，上层拿**上一拍旧 GyroZ 反复积分**——一次瞬时大值被卡住 + 持续 I2C 失败 = 恒定假旋转，与实测恒定步进特征吻合 | F4b-1 |
| 以上全正常但 YAW 仍跳 | `ServiceMpuTask` 的 elapsedMs/dt 单位、STAT 输出处 ±180 wrap、Kal_Yaw 对连续角的处理 | 逐项核对 |

**F4b 必修项（无论诊断结果如何）**：

1. `BMI270_Get_Raw` 读失败路径：GyroX/Y/Z 置 0 + 置 `imu_fault` 标志 + 计数，**禁止沿用旧值继续积分**。
2. 标定校验 bug：`bmi270_driver.c:392` 的 `&&` 改 `||`（现状=三轴全坏才判失败，Z 轴单独坏照样通过）；Z 轴单独用更严阈值 `|gz_sum/100| >= 1` 即失败。
3. 开机标定 3 次失败：不再只 WARN，置 `imu_fault`；`STAT`/`TLM` 增加 `IMU=<OK|FAULT>` 字段，PoseFuser 与 `TURN_YAW` 见 FAULT 拒用 YAW。
4. 新增 V2 命令 `GYROCAL`：按需重跑 `SoftCalibrate_Z(200)`（要求静止 1s），成功则清 fault。板端在每次泊车 session 开始、确认车静止时发一次。
5. 饱和检测：|GyroZ raw| ≥ 32000 持续 >100ms → `imu_fault`。

**F4c 防漂（硬故障修复后再做）**：静止 ZUPT——编码器双轮零速 ≥500ms 且无运动命令激活且 |GyroZ| < 3 LSB 时：① 冻结 yaw 积分；② `gyro_zero_z` 慢速 EMA 重估（α≈0.01/样本）。手搬车防护：门限低 + EMA 慢，真实转动时 GyroZ 远超 3 LSB 不会触发误重零。本项利用"停-看-走"架构（车 90% 时间静止），把残余漂移压到单动作 ≤0.6°。

**验收阶梯（全过才解除 C0 阻塞）**：

```text
1. GDIAG 字段完整、可解释，根因写入修复记录
2. 静止 60s YAW 总变化 < 0.5°; 静止 5min < 1°
3. ZERO_YAW 后 YAW≈0 且保持
4. 手转 +90° 再转回, YAW 回零误差 ≤ 2°
5. MOVE D=-6 直线倒车, |ΔYAW| < 3°
6. 重跑 C0 符号验证, 填齐 configs/chassis_signs.json
```

产出：`docs/autopark_f4_imu_yaw_fix_2026061X.md`（诊断数据 + 根因 + 修复 + 验收记录），GDIAG 原始输出存 `artifacts/autopark_baseline/`。

**B1（P0，板端，半天）分发式串口读线程**
控制器内加后台 reader：按行首 token 分发 `ACK/DONE/TLM/STAT/PWM/ERR`，时间戳入队；主循环消费。原有同步读路径在 `TELEM=0` 时不变。验收：板上 `TELEM=1` 手动 MOVE 一次，JSONL 中 TLM 行数 = 运动时长×5±1，无乱序。

**B2（P0，板端+PC，1 天）PoseFuser 核心**
§4.1–4.4 与 §4.6，写成 `# ===== fusion core =====` 纯函数段。配套 PC 单测 `tools/test_pose_fuser.py`：用手工构造的 TLM 序列（直线 / 定曲率弧）验证传播公式（弧线终点解析解 vs DR 积分，误差 <1%），用注入噪声验证 4.4 门限行为。验收：单测全过；`py_compile` 过。

**C1（P0，实车+固件，1 小时）底盘几何实测**（§5）。

**B3（P1，板端，半天）运动中安全监视**
§4.5 五个门接入 EXECUTING 态，触发即 STOP 并写明 verdict。dry-run 模式下门照常计算、只记录不发 STOP（字段 `would_stop=true`）。验收：dry-run 回放构造的越界 TLM 序列触发 `would_stop`。

**C2+C3（P1，实车，1 个下午）曲率与尺度标定**（§5）
与主计划 §6.2 标定顺序**合并执行**：同一批探针同时产出响应模型样本（视觉 delta）和底盘模型（R_eff、尺度）。从 STE=120 开始。

**B4（P1，PC，半天）对账进响应模型**
`tools/parking_response_model_updater.py` 增读 `fusion_reconcile` 事件：样本附 `r_eff / slip / scale` 字段；verdict=slip 的样本标记不可信、不入 mean_delta。验收：对 C2 日志重算，输出含物理量的 v2 记录。

**B5（P2，PC，半天）融合回放器**
`tools/parking_fusion_replay.py`：读历史 JSONL（vision+TLM），离线重跑 PoseFuser，输出逐步位姿轨迹 CSV 供人工审查/画图。验收：对 C2 的弧线探针，回放末端位姿与实测视觉位姿差 <3cm/4°。

**B6（P2，板端，1 天）预测器升级**
主计划 §7 评分器的 `prior_delta` 预测，替换为基于 `chassis_kinematics.json` 的弧线几何预测（R_eff + 距离尺度 → 槽坐标系 delta → 投影回 px 指标），measured 样本仍优先。验收：对已标定动作，几何预测与实测样本 delta 偏差 <30%。

**B7（P3，板端）盲走末段（L3 能力，需用户点头才开工）**
`final_straight` 相位 + 视觉丢失 + 锚龄 <3s 时，允许 DR-only 倒车，硬上限 8cm、一次为限。前置条件：B2~B5 全过、S5 阶梯通过。

### 与主计划的合流点

```text
主计划 T1/T2/T4 (success criteria/模型工具/回放)  ──┐
F2+F3+F4+C0+B1+B2 (本文 P0 批, F4 阻塞 C0)        ──┤→ 合并后进入 C2 标定 (=主计划 M1 campaign)
C1                                                 ──┘
C2/C3 完成 → 主计划 T3 (action_replanner) 的预测器直接用 B6 几何版
B3 运动中安全门 → 主计划 S4 (两步连续) 的放行前提
```

即：**先打通融合数据链（F2/F3/C0/B1/B2，约 2 天），再开始实车标定 campaign**，让每一发探针都同时喂两个模型。这是比"先标定再融合"少跑一半实车次数的关键排序。

---

## 7. 风险与回退

| 风险 | 缓解 |
|---|---|
| 9600 波特拥塞导致 TLM/DONE 丢行 | 5Hz×65B 预算 + 运动中禁轮询 + DROP 字段监控；丢 TLM>1s 即 STOP |
| IMU YAW 硬故障（2026-06-13 已实测发生） | F4 诊断+修复+`IMU=FAULT` 健康标志；FAULT 时 PoseFuser 退化为里程计 θ + 视觉锚，禁用 TURN_YAW |
| IMU 漂移污染 φ（修复后的常态风险） | F4c 静止 ZUPT + 每动作首尾视觉重锚定，单动作 ≤10s 残余 <0.6°；锚龄超 30s 强制重锚 |
| 运动中视觉帧模糊导致错误校正 | §4.4 双门限 + 小步长 0.3 混合 + 异常计数；最坏情况退化为纯 DR，末端仍有视觉对账兜底 |
| Ackermann 常数错（轮距/轴距占位值） | C1 实测先行；C2 的 R_eff 是端到端实测，即使几何常数有残差也被吸收 |
| 固件改动破坏已验证 V2 链路 | TELEM=0 默认关、逐字节兼容验收；烧录前后跑一遍既有 `PING/STAT/PWM_STAT/MOVE` 冒烟序列 |
| 倒车打滑使里程计虚高 | IMU/里程计劈叉门（§4.5）+ slip 样本不入模型（B4） |
| tick 周期假设错导致 TLM 频率错 | F2 验收实测频率，不信注释 |

回退路径：任何阶段融合链路出问题，`TELEM=0` + 不加新旗标 = 完全回到现行"停-看-走"模式，主计划照常推进。

---

## 8. 一句话路线图

```text
第1天   F2+F3 固件遥测 [✅ 2026-06-13 已完成并烧录验证] / B1 读线程
第2天   F4 IMU YAW 诊断+修复 (GDIAG→根因→F4b→F4c, 当前最高优先) → 重跑 C0 符号
第3天   B2 融合核心+单测 / C1 几何实测
第4天   C2+C3 标定下午场(=主计划M1, 从STE=120开始) / B4 对账入模型
第5-6天 B3 运动中安全门 / B5 回放器 / 进入主计划 S3 人审单步
之后    B6 几何预测器 → 主计划 S4-S6 → (用户批准后) B7 盲走末段
```
