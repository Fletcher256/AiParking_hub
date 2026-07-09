# 自动泊车顶层重建执行规格（Codex 权威总纲）- 2026-06-21

> **本文件是当前唯一权威总纲。** 在它与任何旧文档冲突时，以本文件为准。
> 旧文档（`autopark_codex_execution_plan_20260612.md` / `autopark_fusion_closed_loop_plan_20260613.md` /
> `autopark_final_pose_straighten_plan_20260613.md` / `autopark_l0_closeout_l1_grid_plan_20260613.md` /
> `autopark_perception_robustness_plan_20260613.md` / `autopark_demo_cadence_plan_20260613.md`）
> 降级为**设计参考**，其中的所有标定数值（deg_per_cm、trim、死区、符号、噪声统计、时序）一律视为**过期、待重新现场验证**。
>
> **根本前提（用户指令 2026-06-21）：先前的软件参数未必有效，唯一确定不变的是硬件。**
> 因此本规格的方法论是：**契约先行 → 每个值现场实测 → 单一收口 → 全程可审计**。任何阶段不得引用未经本轮重验的旧参数作为事实。

---

## 0. 方法论（为什么这样组织，Codex 必须内化）

这个项目历史上每一次翻车，根因都是**信任了未经当前验证的参数或符号**：IMU YAW 符号曾翻转、`+x_cm` 曾被误标 forward、感知离群处理方向写反、arm 安全门被运动分支旁路、固件烧录后 YAW 行为突变。结论：

1. **不预设任何标定值。** 旧值只能作为"预期量级 sanity 参考"，永远以本轮现场实测覆盖。
2. **接口契约先确认，行为再验证。** 固件命令集在源码里是确定的（§2），但每条命令的单位、符号、死区、闭环行为都要现场实测。
3. **每个运动出口单一收口。** 所有发往 STM32 的运动命令必须经过唯一函数，安全门在那一处断言，杜绝旁路。
4. **每一步先 dry-run / 离线验证，再实车单步，再连续。** 不跳级。
5. **全程 JSONL 可审计。** 每个决策、每条命令、每次 ACK/DONE、前后状态都落盘，事后能复盘。
6. **车 90% 时间静止（停-看-走架构）= 强物理先验。** 静止时世界不变：大视觉跳变必是噪声、丢帧可安全 hold、IMU 可重新归零。充分利用。

每个 Stage 的任务统一格式：**目的 / 现状审计 / 动作 / 验收 / 产出 / 失败处理**。Codex 按 Stage 顺序推进，Stage 内任务可并行处不另注明即为串行。

---

## 1. 唯一确定的地基：硬件清单（物理事实，不变）

```text
[感知] OS08A20 摄像头, 后置(车尾朝车位) → 泊车 = 倒车入位
       SS928 / 海鸥派 / openEuler Embedded 板端运行 YOLO 分割
[算力] SS928 板:  SSH root@192.168.137.2 (密码 ebaina)
       解释器 /usr/local/bin/python3, 板上无 pip 第三方包 → 板端代码必须纯标准库
[底盘] STM32:
       - 两后轮独立有刷电机 + 各自正交编码器 + 各自速度 PID(闭环)
       - 前轮舵机转向(Ackermann 几何), 舵机名义中位 STE=90, 物理范围约 45-135
       - BMI270 IMU (提供 YAW 航向)
       - 编码器里程计 (积分出 X/Y/D/theta)
[链路] STM32 ↔ 板:  CH341 USB 串口 → /dev/ttyUSB0 @ 9600 8N1 (硬约束 ≈960 B/s)
       YOLO → 板控制器:  UDP 127.0.0.1:24580 (JSON, 车位多边形/检测)
       YOLO → VM 监控:   通过 board_yolo_udp_tee.py 复制到 192.168.137.100 (只监控, 不参与控制)
[开发] PC 工作区 D:\parking_board_agent, venv 解释器 .venv\Scripts\python
       下发板端命令: tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina ...
```

**需要用卷尺/量角器现场测量并记录的物理常数**（Stage 1 用，旧值一律不信）：
- 后轮轮距 `WHEEL_TRACK_CM`（两后轮接地中心间距）
- 前后轴距 `WHEEL_BASE_CM`
- 相机光心到后轴中点的纵向距离 `L_cam_cm`（融合/几何预测的杠杆项需要）
- 车体外廓长宽（用于判断"是否真的停进车位"的几何）

---

## 2. 软件接口契约（固件命令集 = 源码确认，行为待验证）

固件命令集（`SS928_hub/Core/CarProtocol.c` 源码核实，2026-06-21 确认存在）。格式：`@<seq> <CMD> [args]\r`，回车结尾；STM32 回 `ACK <seq> <CMD>` → 执行 → `DONE <seq> <CMD> [末态]` 或 `ERR <seq> CODE=<code> [末态]`。

| 类别 | 命令 | 用途 | 行为待验证点 |
|---|---|---|---|
| 查询 | `PING` `VER` `STAT` `PWM_STAT` `GDIAG` `GET <param>` | 健康/版本/状态/舵机/陀螺诊断/读参 | STAT 字段集、GDIAG 字段集 |
| 运动 | `MOVE D=<cm> V=<gear>` `ARC D=<cm> STE=<deg> V=<gear>` `TURN <deg>` `STOP` `CANCEL` `SERVO A=<deg>` | 直行/弧线/原地转/急停/取消/单设舵机 | **D 单位与符号、死区、STE→曲率、TURN 是否可靠** |
| 标定/归零 | `GYROCAL` `ZERO_YAW` `ZERO_ODOM` `ZERO_ALL` | 陀螺零偏重标/航向归零/里程计归零/全归零 | 归零后字段是否真清零 |
| 配置 | `SET <param>...` `SAVE_CFG` `LOAD_CFG` `DEFAULT_CFG` `MODE <m>` `TEL ON\|OFF` `AUTO` | 在线改参/持久化/模式/遥测开关 | TEL 遥测行格式与频率 |

**STAT 字段（待 Stage 0 现场确认仍是这些）**：
`STAT <seq> MODE=.. RUN=.. DIR=.. SPD=.. ANG=.. YAW=.. X=.. Y=.. D=.. VEL=.. DROP=.. IMU=..`

**关键契约红线**：
- 旧 memory 记 "D 负值=倒车""左转=YAW增" 等——**全部作废，Stage 1 重测**。
- `ZERO_ODOM` / `ZERO_YAW` 是本轮要充分利用的新能力：每个动作前归零 → 让 STAT 的 X/Y/D/YAW 直接是"本动作增量"，消除累计量符号歧义。
- 串口 9600 是硬天花板：遥测设计、每步串口往返次数都受其约束（§Stage 7）。

---

## 3. 闭环总体架构（三环 + 数据流 + 坐标系）

```text
┌──────────────── 板端 board_parking_controller.py (纯标准库) ────────────────┐
│ [外环 每动作一次 ~0.2-1Hz]            [中环 运动期间 ~5-10Hz, 可选]            │
│  感知→状态→规划→选一个短动作           运动遥测(TEL)位姿传播 + 运动中安全监视    │
│   │                                     │(本轮先不强求, Stage 8 再启用)        │
│   ▼ 经唯一出口 send_motion() 下发        ▼                                     │
└────────────────┬──────────────────────────────────────────────────────────┘
   /dev/ttyUSB0 9600 8N1  (↓命令 MOVE/ARC/STOP  ↑回执 ACK/DONE/ERR/TLM)
┌────────────────▼──────────────────────────────────────────────────────────┐
│ [内环 STM32 50-100Hz, 硬件既有] 轮速PID ← 编码器 | Ackermann差速 ← 舵角        │
│   里程计积分 X/Y/D/theta | 距离终止 | IMU YAW | 超时/CANCEL 保护              │
└────────────────────────────────────────────────────────────────────────────┘
   感知: OS08A20 → YOLO seg → UDP 127.0.0.1:24580 (不改动)
```

**坐标系与符号（Stage 1 用实验定死，写进 `configs/chassis_signs.json`，不靠猜）**：
- 槽坐标系：原点=车位入口边中点，**+y 指向车位内部**，+x 沿入口边与图像 x 同向。
- 车辆参考点 = 后轴中点。位姿 `(x_s, y_s, φ)`，φ=倒车运动方向与 +y 夹角，车尾正对入口时 φ=0。
- 与视觉状态映射：`x_s ≈ slot_lateral_cm`、`y_s ≈ -slot_y_dist_cm`、`φ ≈ slot_heading_err_deg`（**符号系数 Stage 1 实测**）。

---

## 4. 能力阶梯与里程碑（验收口径）

| 等级 | 初始位姿范围 | 新增能力 | 里程碑判据 |
|---|---|---|---|
| **L0** | 固定标定位姿 ±2cm/±2° | 单步响应已标定 + 端到端泊车 | 同起点 5 回合 ≥4 次"停进且平行"(\|终态航向\|≤2°) |
| **L1** | 横向±5cm/航向±5°, 车位全可见 | 每步重规划自动连续 | 3×3 网格 ≥7/9 格成功, 全程无安全违规 |
| **L2** | 横向±15cm/航向±10° | 前进修正动作 + 相位状态机 | L2 网格成功矩阵(按 L1 暴露的失败立项) |
| L3 | 车位局部可见 | 局部可见状态估计 + 末段盲走 | 远期 |
| L4 | 车位初始不可见 | 搜索/建图 | **不承诺** |

**当前所在级：需要从 Stage 0 起重新验证后，才能确认实际停在哪一级。**（"板端做了改动"+"参数失效" → 不假设仍在 L0/L1。）

**明确不承诺**：动态障碍避让、非标定地面泛化、平行侧方位泊车（本项目是垂直倒车入位）、厘米级绝对定位。

---

## 5. 执行阶段（核心，逐步对 Codex 指导）

> 通用纪律：板端代码纯标准库；改后 `python3 -m py_compile` 自检；上传用 `board_sftp_put.py`，执行用 `board_auto_ssh.py`；
> 每个实车任务必须 `--arm` + `/tmp/parking_armed` 双门，跑完手动删 arm file；所有运行落 JSONL 到 `/tmp/...` 再回收到 `artifacts/autopark_baseline/`；
> 每个 Stage 结束写一份 `docs/autopark_rebuild_stageN_2026XXXX.md` 记录现状审计结论 + 实测值 + 验收。

---

### Stage 0 — 链路复活与接口现状审计（半天，先软后硬）

**目的**：在动任何参数前，确认硬件链路通、固件命令集与回执格式与 §2 一致、控制器能纯 dry-run 跑通。

**S0.T1 串口与固件契约确认**
- 动作：`board_auto_ssh.py` 下发安全查询序列 `PING / VER / STAT / PWM_STAT / GDIAG`（只读，不运动）。
- 验收：PING→PONG；VER 回 `FW=.. BAUD=9600 PROTO=..`；STAT 字段集与 §2 一致（如不一致，**以现场为准更新 §2 表**）；GDIAG 返回陀螺诊断字段。
- 产出：`artifacts/autopark_baseline/s0_stm32_contract_2026XXXX.json`（记录每条命令原始回执）。
- 失败：CH341 枚举成 `ffff:3733`=供电/线缆问题；`/dev/ttyUSB0` 不在→跑 `board_ch341_autobind.sh`。

**S0.T2 感知链路确认**
- 动作：确认板端 YOLO + UDP tee 在跑；板端抓 60s `UDP 127.0.0.1:24580`，统计检测率/置信度/bbox。
- 验收：检测率 >95%、conf 在合理区间、bbox 稳定（量级 sanity，不记为标定值）。
- 产出：`s0_perception_link_2026XXXX.json`。

**S0.T3 控制器现状审计（最重要）**
- 动作：读当前 `tools/board_parking_controller.py`，列出：① 现有 `--strategy` 选项；② 所有发运动命令的代码位置；③ 是否已有单一 `send_motion()` 收口；④ 现有 CLI 旗标；⑤ 读取哪些 config。
- 验收：产出一份"控制器现状清单"，明确标注哪些安全门已实现、哪些运动出口未收口（旁路风险）。
- 产出：`docs/autopark_rebuild_stage0_2026XXXX.md` 的"控制器审计"段。
- **这是后续所有 Stage 的基线认知，不可跳过。**

**S0.T4 纯 dry-run 冒烟**
- 动作：`--replanner-dry-run`（或等效 no-motion 模式）板端跑 60s，确认不开串口、不发运动、JSONL 字段齐。
- 验收：无任何运动命令发出；日志有状态行。

---

### Stage 1 — 传感器真值重标（实车，人在场，1 天）—— 不信任何旧符号/旧尺度

**目的**：重新实测 IMU 符号与质量、里程计符号与尺度、舵机机械中位、视觉符号，全部写进**新生成**的 `configs/chassis_signs.json`（旧文件备份后重写）。

**S1.T1 IMU YAW 质量与符号**
- 动作：①静止 60s 连续 STAT，测 YAW 漂移率；②`ZERO_YAW` 后再测；③手转车顶视顺时针 ~90° 读 YAW 变化定符号；④`GDIAG` 记录零偏/量程/dt。
- 验收：静止 60s YAW 漂移 <0.5°（不达标→先跑 `GYROCAL` 重标，仍不行→F4 类诊断，YAW 暂判不可用并记录）；顺时针旋转的 YAW 符号明确。
- 产出：`chassis_signs.json: yaw_cw_positive`（实测填）、`s1_yaw_quality_2026XXXX.json`。

**S1.T2 里程计符号与尺度**
- 动作：`ZERO_ODOM` 后发 `MOVE D=-10 V=1`（小步、车架空或安全空地），读 DONE/STAT 的 X/Y/D；重复正负向。
- 验收：确定倒车时 D 的符号、实走 cm 与命令 D 的关系（**死区在 Stage 2 精测，这里先定符号 + 量级**）。
- 产出：`chassis_signs.json: odom_d_reverse_negative / odom_x_right_positive`。

**S1.T3 舵机机械中位 trim**
- 动作：`ARC D=-10 STE=90 V=1`（**必须用 ARC，不用 MOVE**——MOVE 的航向保持会掩盖舵机偏置），读 Δyaw；若 |Δyaw|>1° 则 STE=88/92/94 二分到 |Δyaw|≤0.5°。
- 验收：得到 `servo_center_trim_ste`（实测）。注意：若各档 Δyaw 都很小说明 trim≈90，不强求。
- 产出：写入 `chassis_kinematics.json: servo_center_trim_ste`。

**S1.T4 视觉横向符号**
- 动作：车摆车位明显偏左、偏右各一次，dry-run 读 `slot_lateral_cm` 符号。
- 验收：`vision_lateral_left_negative` 实测确定。**前提**：YOLO 当前能稳定看到车位（否则先调好再做）。
- 产出：`chassis_signs.json: vision_lateral_left_negative`。

**Stage 1 总产出**：全新 `configs/chassis_signs.json`（4 个符号字段全部 `verified_date=2026XX`，无 null）；`L_cam_cm / WHEEL_TRACK_CM / WHEEL_BASE_CM` 卷尺量值记入文档。**任一符号为 null，Stage 2+ 不得开工。**

---

### Stage 2 — 底盘运动学重标（实车，1 个下午）—— 重建 chassis_kinematics.json

**目的**：重测 MOVE/ARC 的死区、四档 STE 的曲率响应、左右对称性。旧 `chassis_kinematics.json` 备份后重建。

**S2.T1 距离死区（MOVE 与 ARC 分别测）**
- 动作：`ZERO_ODOM` 后逐发，记 DONE.D 与 STAT.D：
  ```text
  MOVE D=-4 / D=-6 / D=-10 V=1      # MOVE 死区 + 滑行
  ARC D=-3 / D=-4 STE=120 V=1       # ARC 小距离死区(左)
  ARC D=-3 / D=-4 STE=60  V=1       # ARC 小距离死区(右), 左右可能不同
  ```
- 验收：得 `move_deadband_cm`、`arc_deadband_cm`、`arc_min_effective_cmd_cm`（实走≥1cm 的最小命令）、`coast_after_done_cm`（STAT.D−DONE.D）。
- 产出：写入新 `chassis_kinematics.json`。

**S2.T2 四档曲率 deg_per_cm**
- 动作：每档 `ZERO_ALL` 后发 `ARC D=-6 STE=<60/75/105/120> V=1`，各 ≥2 次，记 Δyaw_stat / D_stat，算 `deg_per_cm = Δyaw/D`、`R_eff = D/rad(Δyaw)`。从 STE=120 起（历史最可靠方向）。
- 验收：同档两次 deg_per_cm 偏差 <15%；记录左右对称比 `|60|:|120|`、`|75|:|105|`。
  **重要认知**：历史数据显示左右严重不对称（软档比值曾达 1.77），且仅靠 trim 解释不了 → **counter_steer 必须用每档实测 deg_per_cm，严禁假设左右对称**。
- 产出：`chassis_kinematics.json: steer_curvature[]`（每档 deg_per_cm/R_eff/n/samples）。

**S2.T3 提取工具与数据卫生**
- 动作：审计/修 `tools/extract_chassis_kinematics.py`，确保：样本带 `source_log/log_date/yaw_source_ok`、剔除小距离死区样本与任何可疑日志、能从 `counter_steer_result` 事件持续积累样本。
- 验收：重算报告含每档 n 与剔除数；本轮全部样本来自本轮实测（不混旧日志）。
- 产出：`artifacts/autopark_baseline/chassis_kinematics_audit_2026XXXX.json`。

---

### Stage 3 — 感知→状态层验证与滤波加固（板端+PC，1 天）

**目的**：确认 `slot_relative_state` 在当前模型/场景下稳定，重测噪声分布，修复滤波鲁棒性，让"框跳/框消失"不再误触发停车。

**S3.T1 状态稳定性重测**
- 动作：固定场景静止 dry-run 60s，统计 `slot_x_err_px / heading / lateral / min_margin / pose_quality` 的 mean/stdev。
- 验收：各量 stdev 在可用区间（旧参考：x_err~0.5px、heading~0.18°，**仅参考**）；输出本轮真实噪声 3σ。
- 产出：`tools/perception_noise_profile.py` 报告 + `s3_state_noise_2026XXXX.json`。

**S3.T2 滤波鲁棒性（修方向性 bug）**
- 动作：审计 `SlotStabilityFilter`。必修三点：① `fused()` 均值→**中值**（纯标准库 median）抗离群；② 离群 gate 与**窗口中值**比较，跳变帧**丢弃保窗**（不是清窗信新帧——这是历史 bug），连续 K=3 帧一致才认定真移动；③ 视觉丢失改 **hold+grace**（静止期 coast 上一稳定态过宽限期），STOP **分级去抖**。
- 安全红线：**压线/越界门不去抖（一帧即停）**；coast 态只维持现状判定，**绝不发起新运动**。
- 验收：构造序列单测（注入单帧跳变→不清窗不 STOP；注入 0.6s 丢失→grace 内不 STOP；注入压线→立即 STOP 未被削弱）。`tools/test_perception_filter.py` 全过。
- 产出：阈值写 `configs/perception_filter.json`（由 S3.T1 噪声反推，非拍脑袋）。

**S3.T3 状态字段补全**
- 动作：按需补 `slot_visible_ratio / entry_edge_visible / vision.lost_ms / motion 记账`（终段盲区判定与安全门需要）。
- 验收：dry-run 日志含新字段。

---

### Stage 4 — 单步规划与执行闭环（板端，1-1.5 天）—— 收口 + dry-run + 单步实车

**目的**：建立"读稳定状态→评分选一个短动作→经唯一出口执行→停车重观察"的安全单步闭环，并用实车单步重建响应模型。

**S4.T1 运动出口单一收口（安全基础设施，最高优先）**
- 动作：把所有发运动命令的位置收口到唯一 `send_motion(cmd, ...)`：内部断言 `armed` + `/tmp/parking_armed` + steps/total caps；`STOP`/`CANCEL` 豁免；dry-run 永不进入。审计并消除 vision-lost DR、blind-finish 等旁路。
- 验收：grep 确认运动命令发送点只剩 `send_motion` 内部一处；不带 `--arm` 跑所有策略分支（含 vision-lost）无任何运动发出。
- 产出：控制器更新 + 审计说明。**这条不过，后续实车一律不许开工。**

**S4.T2 评分器与响应模型对齐**
- 动作：审计 `action_replanner` 评分逻辑。硬规则：① 实车自动执行只允许"该状态桶有 measured 且 verdict≠worsened"的动作；② 未标定动作只能走 `primitive_probe` 人工标定，不得自动执行；③ 抗抖动：换向惩罚+滞回+同动作连败 2 次熔断 STOP+进度看门狗。
- 验收：`tools/parking_replay_planner.py` 回放历史/dry-run 状态行，静止时动作切换 ≤2 次、右偏选右修正方向正确（import 板端同一份评分函数，禁止两份逻辑）。

**S4.T3 单步实车重建响应模型**
- 动作：胶带框复位（dry-run 10 帧确认初始状态在窗口内）。对动作库逐个 `primitive_probe`，每个同位姿 ≥3 次，记 pre/post 10 帧均值、delta、verdict（显著性按 S3.T1 实测 3σ）。从 STE=120 起。
- 验收：每个动作 ≥3 样本入 `parking_action_response_model.json`（按状态桶 + confidence 公式）；两次方向相反则查复位质量重测。
- 产出：全新 `parking_action_response_model.json`（本轮实测，不混旧样本）。

---

### Stage 5 — 终段收尾：盲倒 token + counter_steer 摆正（板端，1 天）

**目的**：解决"停进但略歪"。根因：弧线修横向会把横向误差转成航向误差，直线盲倒将其冻结 → 需反打弧摆正 + 死区补偿的盲倒距离。

**S5.T1 死区补偿的盲倒**
- 动作：终段 YOLO 盲区用一次性 `final_blind_token`（写入门槛：`|lateral|≤1.5cm` 且 `|φ|≤2°` 且 margin 达标；执行即 STOP 即 consumed；禁止连续盲倒）。盲倒距离 = 剩余深度 + `move_deadband` − `coast`（用 Stage 2 实测值），上限 ~10cm。
- 验收：单回合盲倒后深度达标，无连续盲倒。

**S5.T2 counter_steer 反打弧（参数化动作）**
- 动作：`straighten_or_enter` 相位（`|lateral|≤1.5cm` 且 `|φ|>2°`）执行：方向取消 φ 的一侧（由 chassis_signs+S2 实测方向查表，**不写死**）；距离 `d_cmd = |φ|/deg_per_cm(档) + arc_deadband`，且 ≥`arc_min_effective_cmd_cm`，上限 6；|φ|≥3° 用硬弧、<3° 用软弧。最多 2 次，变差即 STOP。
- 终段决策表：
  ```text
  |φ|<2° 且 |x|<1.5cm        → 直线盲倒(写 token)
  2°≤|φ|≤6° 且 |x|<1.5cm     → counter_steer 消航向 → 再观察 → 达标则盲倒
  |x|≥1.5cm                  → 不写 token, 退回可见段先修横向(单弧无法同时清 x 和 φ)
  ```
- 验收：dry-run 喂 φ=+4°/-4°/+1° 三态，方向/档位/距离与手算一致；实车单回合反打后 |φ| 改善。
- 产出：`counter_steer_decision` / `counter_steer_result` 事件落盘，自动回流 S2.T3 系数样本。

**S5.T3 终态量化**
- 动作：用 IMU 短时 Δyaw 量化终态航向（`heading_token + 符号映射(yaw_final−yaw_token)`），输出 `final_pose_report{final_heading_deg, lateral_est, depth_est, verdict}`。
- 验收：与目视对照 3 回合，数字与肉眼一致。

---

### Stage 6 — L0 端到端回归（实车，半天）—— 宣告里程碑

**目的**：同起点 5 回合全自动泊车，宣告 L0。

- 协议：胶带框复位→dry-run precheck→`action_replanner` 实车（counter_steer+token 全开，`--max-motion-steps 8 --max-total-cm 50`，全程 JSONL）→`final_pose_report`+俯视照片。
- 判定：单回合通过 = `parked_straight`(|终态航向|≤2°)且深度达标；**L0 通过 = 5 回合 ≥4 次**。安全门触发不算失败（记录后重摆继续）；连续 3 回合 straighten_failed 或方向打反 → 中止回 Stage 2/5 查值。
- 产出：`docs/autopark_l0_regression_2026XXXX.md` + 日志/照片入 `artifacts/.../l0_regression/`；通过则在 `autopark_long_term_memory.md` 顶部记"L0 达成(日期)"。

---

### Stage 7 — 演示质量：节奏感与提速（板端，可与 Stage 6 并行）

**目的**：消除步间过长停顿，达到"有节奏感的阶段倒车"演示效果。**只砍软件浪费，不砍物理必要的停稳/观察。**

- **S7.T1 插桩先量化**：每步 JSONL 记 `step_timing`（drain/STAT/move/settle/observe 各段 ms），先测后砍。
- **S7.T2 去 drain 浪费（最大收益）**：`send_cmd` 的固定 0.4s drain 改为 **seq 对齐**——按 `@seq` 只认领本次回执、跳过旧残留，drain 缩到 ≤0.05s flush。既省 ~2s/步又更可靠（杜绝错配旧 DONE）。单测：含旧 seq 残留的字节流只认本 seq。
- **S7.T3 省冗余串口往返**：DONE 已带末态 → 省 post-STAT；TEL 改 session 级常开（如需遥测）→ 省每步 ON/OFF；pre-STAT 按需。
- **S7.T4 settle 实测下调 + 节拍**：settle 由"DONE 后 VEL 归零且 X/Y/D 不再变"的实测停稳时间定（不可为节奏归零）；可选 `--demo-cadence-sec` 把每步钳到均匀节拍（实际<T 补足、>T 不延长）。
- 合并收益：S7.T2 的 seq 对齐 + 出口收口可与 S4.T1 一起做（同一次重构）。
- 验收：`step_timing` 显示步间停顿从基线大幅下降、节拍均匀；功能回归不变（dry-run 日志对照）。

---

### Stage 8 — L1 扩范围（实车，1-2 天，L0 通过后）

**目的**：把成功包络从固定起点推到横向±5cm/航向±5°。

- **S8.T1 几何预测器**：评分器对未实测桶的预测从 prior 换成几何计算（用 S2 的 deg_per_cm/R_eff + S1 的 L_cam 杠杆项：`Δ视觉lateral = R_eff(1−cosΔφ) + (y_dist+L_cam)·sinΔφ`）。验收：对已有 measured 样本回测偏差 <30%。
- **S8.T2 3×3 网格回归**：横向{−5,0,+5}cm × 航向{−5,0,+5}° 各 2 回合（18 回合）。每格失败必归因（`gate_no_token`/`straighten_failed`/`lateral_unreachable`/`vision_lost_early`/`safety_stop`）。
- 判定：≥7/9 格成功且无安全违规 = L1 达成。
- 产出：`docs/autopark_l1_grid_2026XXXX.md` 成功矩阵。矩阵驱动下一步：`lateral_unreachable` 集中 → L2 `forward_correct` 立项；`gate_no_token` 集中 → 响应模型补桶清单。

---

### Stage 9+ — 远期（不在本轮关键路径，按 L1 矩阵立项）

- **L2 前进修正** `forward_correct`：前方无感知，硬上限 4cm、连续≤2 次、累计前进≤12cm，先标定后入库；`recover_forward` 相位。
- **运动中闭环（融合中环）**：TEL 5Hz 遥测 + PoseFuser 运动中位姿传播 + 运动中 early-stop（IMU/里程计劈叉检测打滑、预测压线提前停）。当需要更宽范围或运动中安全时再激活。
- **Reeds-Shepp 简化版**：仅当每档 deg_per_cm ≥5 样本、R_eff 稳定后，作为候选**序列生成器**接入现评分架构（仍每步只执行第一步）。RL / Hybrid A* 在本传感器配置下不立项。

---

## 6. 安全总纲（贯穿所有 Stage，任何改动不可删）

```text
运动双门:     无 --arm 不动; 无 /tmp/parking_armed 不动
dry-run:      永不发运动命令
唯一出口:     所有运动命令经 send_motion(), 安全门在该处断言(Stage 4.T1)
视觉丢失:     非终段丢失 >0.5s → STOP; 终段仅一次性 token 盲倒
压线/越界:    line_risk / min_margin<floor → 立即 STOP(不去抖)
状态发散:     连续异常 → STOP; 同动作连败 2 次 → 熔断 STOP
距离上限:     总运动距离/步数超 cap → STOP
STM32 异常:   ACK/DONE/ERR/STAT 异常 → STOP
退出兜底:     进程退出前再发一次 STOP
实车纪律:     先 dry-run → 单步 → 两步 → 多步, 不跳级; 人在场
coast 约束:   coast/hold 态只维持现状判定, 绝不发起新运动
未标定动作:   实车自动执行只允许 measured 且非 worsened; 其余只能 primitive_probe
```

---

## 7. 配置文件归属（本轮全部重新生成，旧文件先备份 `.bak`）

| 文件 | 内容 | 重建于 |
|---|---|---|
| `configs/chassis_signs.json` | 4 个符号 + 物理常数 | Stage 1 |
| `configs/chassis_kinematics.json` | 死区/滑行/四档曲率/trim | Stage 2 |
| `configs/perception_filter.json` | 滤波窗口/gate/grace/去抖阈值 | Stage 3 |
| `configs/parking_action_library.json` | 动作库 + allowed_phases + requires_measured | Stage 4 |
| `configs/parking_action_response_model.json` | 按桶 measured 样本 | Stage 4 |
| `configs/parking_success_criteria.json` | done/abort 判据 | Stage 4 复核 |

---

## 8. 风险与回退

| 风险 | 缓解 |
|---|---|
| 旧参数残留误导 | 本规格强制每值重测；旧 config 先 `.bak` 再重建 |
| IMU YAW 再次故障 | Stage 1 先验证；`IMU=FAULT` 时禁用 YAW，PoseFuser/TURN 退化 |
| 左右弧不对称 | counter_steer 用每档实测 deg_per_cm，不假设对称 |
| 命令 D 与实走不符 | Stage 2 实测死区/滑行，规划用实测值 |
| YOLO 跳变/丢失误停 | Stage 3 中值+丢弃保窗+hold/grace；压线门不去抖 |
| arm 门被旁路 | Stage 4.T1 单一出口收口 + grep 验收 |
| 9600 串口拥塞 | 省冗余往返(Stage 7)；TEL 仅按需；DROP 监控 |
| 步间停顿毁演示 | Stage 7 去 drain + 省 STAT + 节拍 |

**全局回退路径**：任何阶段出问题，回到"纯 dry-run + 不带 --arm"= 零运动安全态；逐 Stage 重新验证。

---

## 9. 执行总览与记账规则

```text
Stage 0 链路/接口审计(半天) → Stage 1 传感器真值(1天) → Stage 2 运动学(半天)
  → Stage 3 感知加固(1天, 可与2并行PC部分) → Stage 4 收口+单步闭环(1.5天)
  → Stage 5 终段摆正(1天) → Stage 6 L0回归(半天) ┐
                                                  ├ Stage 7 演示提速(并行)
  → Stage 8 L1扩范围(1-2天) → Stage 9+ 远期        ┘
关键路径里程碑: Stage6 过 = L0; Stage8 过 = L1
```

记账规则：
- 每个 Stage 结束写 `docs/autopark_rebuild_stageN_2026XXXX.md`：现状审计结论 + 实测值表 + 验收结果 + 失败归因。
- 每完成一个任务，在本文件对应任务后追加 `[done YYYY-MM-DD, 见 docs/xxx.md]`。
- 实测值只进 config 文件 + Stage 文档，**不写回本规格正文**（正文是流程，不是数据）。
- 重大结论（符号、链路、故障）同步更新 memory（`stm32_v2_link` / `project_autopark_master_plan` 等）。
```
