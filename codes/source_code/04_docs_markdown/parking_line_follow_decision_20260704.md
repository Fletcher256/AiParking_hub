# 直线跟踪倒车决策算法（line_follow decision core）— 2026-07-04

## 一句话

用一条**工业验证过的控制律**替换 h1 结构化阶段的"候选枚举 + 多权重打分"决策层：
饱和临界阻尼直线跟踪律（量产 APA 走廊段的标准做法）+ 闭环 rollout 可行性预演 +
Reeds-Shepp 式前进 shuffle 搜索。执行壳（锁定、积分、视觉修正、安全门、成功判据、
终端 shuffle 兜底）完全复用已验证的 `diy_first_frame_path_parking` 链路，一个开关切换、
默认关闭、可随时回退。

## 文件

```text
tools/parking_line_follow_decision.py        决策核心（纯标准库，可直接上板）
tools/test_parking_line_follow_decision.py   模块单测 19 项
tools/test_h1_line_follow_integration.py     控制器集成测试 7 项
tools/board_parking_controller.py            新增 --diy-path-structured-decision 开关
artifacts/line_follow_decision_20260704/     蒙特卡洛验证报告
```

## 算法

### 1. 状态与运动模型（复用 2026-07-02 修复后的 slot 系积分器）

```text
slot 系状态:  y   剩余深度 cm
             l   横向偏差 cm（左负）
             ψ   航向误差 deg（顺时针正）

倒车一步(地面距离 d, 舵角曲率 κ deg/cm):
  ψ_mid = ψ + κ·d/2
  y ← y − d·cos(ψ_mid);  l ← l + d·sin(ψ_mid);  ψ ← ψ + κ·d

前进一步: 平移取反；yaw 方向由 forward_yaw_sign 控制，默认 -1 = 经典阿克曼取反
  （2026-07-04 复核：SS928_hub 内无前进 ARC 实测样本；当天实车 D=+ shuffle
  日志显示同 STE 前进/倒车 yaw 反号，因此默认恢复为 -1。若后续补充前进
  ARC 标定且证明同号，可用配置覆盖为 +1。）
指令距离与地面距离: ground = D − arc_deadband(1.95) + coast(0.275)
```

### 2. 控制律（每步停车重规划 = 滚动时域）

```text
κ_desired = −(2/λ)·sin(ψ) − (l − l_target)/λ²      [rad/cm]
λ = clamp(0.35·y_remaining, 8, 16) cm
κ 饱和到实测极限 [−1.203 (STE60 左), +0.825 (STE130 右)] deg/cm
STE = 标定曲率表分段线性反查（只用实测行 60/75/80/85/90/100/105/110/120/130）
```

性质（教科书结论，量产 park-assist 同款）：

- 小误差时闭环为 `l'' + (2/λ)l' + l/λ² = 0`，**临界阻尼、无超调**，收敛长度 ≈ 3λ。
- 大误差时饱和 → 自动退化为**最大曲率双弧 S 线**（几何最短横向修正）。
- 一条律覆盖 lateral_capture / heading_payback / fine_approach 全部旧阶段，
  无阶段切换阈值、无 26 个打分权重。

### 3. 可行性预演（rollout）

每次决策前用同一策略做无噪前向仿真（≤40 步闭式计算，<1ms）：
预测到达目标深度时的终值 (l, ψ)。**落进成功框 → 直接倒车；落不进 → shuffle 搜索**。

关键物理事实（本项目底盘）：κ_max 只有 0.83~1.2 °/cm（r_min 69/48 cm），
纯倒车可修横向 ≈ κ·s²/4：s=25cm 时只有 2~3cm，s=45cm 时 7~10cm。
**横向大偏差在纯倒车下物理不可达**——这是历史上横向收不敛的根本原因，
不是调权重能解决的。

### 4. 前进 shuffle（Reeds-Shepp 式换向段）

预演不可达时，在 7 个实测舵角 × 1..4 步链长上搜索前进段：对每个候选，
积分前进段后**再跑一遍倒车预演**，评分 =
`(不可达罚 1000) + 10·横向超差 + 3·航向超差 + 0.15·总路程`，
严格优于"继续倒车"才执行（滚动时域只执行第一步前进）。
"该往哪边打、打多远"从物理预演里自然涌现，不需要 ψ* 启发式。

精度原则：**门限松的是安全门，不是精度判据**——预演落不进成功框就 shuffle，
不带 1.5× 迟滞（历史教训：6/8/10 阈值缝隙里 7.48° 歪着判 parked）。

### 5. 门（刻意松，只有这些）

```text
决策核心内:  |l| ≤ 40cm、|ψ| ≤ 65°（既有松边界）→ stop_bounds
执行壳既有:  max_total_cm / max_steps 预算、no-motion/arm 门、视觉丢失策略
已删除:      clearance 采样罚、cross-zero 罚、phase mismatch、requires_measured、
            long-step 门、strong-heading 政策（对 line_follow 行 bypass）
```

## 验证

### 单元/集成（全部通过）

```text
tools/test_parking_line_follow_decision.py   19 项:
  曲率表插值往返/单调/钳位、控制律符号方向(左右/航向)、运动模型往返、
  无噪全网格收敛(105 姿态含 shuffle)、纯倒车包络收敛、深度封顶、可序列化
tools/test_h1_line_follow_integration.py      7 项:
  plan.v2 契约、倒车/前进行为映射、depth_reached/stop_bounds 空 plan、
  legacy 开关不受影响、config json 覆盖
既有 test_perception_filter / test_parking_line_accumulator 仍 PASS
```

### 蒙特卡洛（h1 实际运行参数：target_y=2.5, lat_tol=4.0, head_tol=6.0）

噪声模型全部来自项目自己的标定数据：每行曲率 CV（2~19%）+ 每 run 5% 系统偏差、
死区/滑行散布、里程漂移逐步累积 + 70% 概率视觉重锚（残差 σ=1.0/0.8cm/0.8°）、
初锁误差 σ=(1.5, 1.2, 1.5°)。

```text
网格: y∈{35,45,55} × l∈{−12..+12} × ψ∈{−20°..+20°} × 30 seeds = 3150 runs
     （网格刻意包含大量纯倒车物理不可达的初始姿态）

结果: 3150/3150 到达目标深度，0 例越界，0 例撞预算
     横向终值  p50=0.41cm  p90=1.00cm  p99=1.82cm   ← 对比历史 10cm 级偏差
     航向终值  p50=2.1°    p90=4.7°    p99=6.5°
     成功率    5cm/8°: 99.9%   3cm/5°: 92.5%   2cm/3°: 65.8%
     步数      p50=10  p90=15  max=37；51% 的 run 用到 shuffle
报告: artifacts/line_follow_decision_20260704/mc_report_h1_params.json
     （模块默认参数版: mc_report.json）
```

## 运行方式

默认完全不变（`legacy`）。启用新决策核心只加一个参数：

```powershell
# 本地 dry-run（已验证可跑）
.\.venv\Scripts\python.exe tools\board_parking_controller.py `
  --dry-run --strategy diy_first_frame_path_parking `
  --diy-path-profile h1_structured_phase_parking `
  --diy-path-structured-decision line_follow `
  --listen-host 127.0.0.1 --listen-port 24685 `
  --chassis-signs-json configs\chassis_signs.json `
  --chassis-kinematics-json configs\chassis_kinematics.json `
  --success-criteria-json configs\parking_success_criteria.json `
  --perception-filter-json configs\perception_filter.json `
  --log-jsonl artifacts\line_follow_dryrun.jsonl
```

板端部署需同步三个文件到 `/opt/parking/autopark/`：

```text
board_parking_controller.py
parking_controller_core.py         ← 控制器模块化后抽出的配置/安全判据核心
parking_line_follow_decision.py    ← 新增，缺失时自动回退 legacy（fail-closed）
```

单独试算一步决策 / 看完整预演轨迹：

```powershell
.\.venv\Scripts\python.exe tools\parking_line_follow_decision.py --decide "45,-8,12"
.\.venv\Scripts\python.exe tools\parking_line_follow_decision.py --rollout "45,-8,12"
```

微调（不加 CLI 参数，一个 JSON 全覆盖）：`--diy-path-line-follow-config-json overrides.json`，
可覆盖键见 `parking_line_follow_decision.DEFAULT_CONFIG`
（λ 范围、步长档、shuffle 候选舵角、松边界等）。

## 实车建议

1. 先跑一次实车对照：同一初始姿态各跑 legacy 和 line_follow，尺量对比。
2. `--diy-path-max-total-cm` 建议放宽到 150（shuffle 需要路程预算；蒙特卡洛
   p99 总路程 < 150cm）。
3. 前进段曲率用的是倒车标定取反的近似（与 terminal_shuffle 同源）；如果 shuffle
   后横向落点系统性偏，标定 2~3 个前进 ARC 样本填进
   `terminal_shuffle_forward_kinematics` 即可，builder 自动优先使用。
4. 决策日志在 candidate 行的 `line_follow_decision` 字段里：`law`（律的各项）、
   `rollout`（预演终值）、shuffle 时的 `shuffle_score` / `continue_reverse_score`，
   每一步"为什么这么打"可完整复盘。

## 2026-07-08 前进修正收紧

实车反馈：有些姿态明明可以继续倒车修正，控制器却先前进；而且前进第一步有时会让车身角度更差。

已收紧规则：

```text
1. 纯倒车预演如果能到目标深度，横向已达标，角度只是略超标，
   优先继续短倒车，不立刻前进。
2. 前进修正的第一步必须让角度变好；
   如果第一步让车更歪，禁止选这个前进方向。
3. 关闭 0.25cm 的提前到深度窗口；
   只有真的到目标深度后才进入“深度已到”。
```

旧日志复算结果：

```text
y=8.174,  lateral=-2.480, heading=11.084:
  原先：ARC D=+8.0 STE=75 V=1
  现在：ARC D=-5.0 STE=77 V=1

y=14.319, lateral=-3.666, heading=16.284:
  原先：ARC D=+8.0 STE=60 V=1
  现在：ARC D=-5.0 STE=72 V=1

y=4.824, lateral=-1.450, heading=8.368:
  原先：ARC D=+8.0 STE=100 V=1
  现在：ARC D=-4.0 STE=70 V=1
```


## 2026-07-08 末端成功条件二次收紧

当前默认实车链路已继续收紧：

```text
target_y_cm = 1.5
success_heading_tol_deg = 3.0
bottom_depth_success_y_cm = 2.0
terminal_shuffle_heading_trigger_deg = 3.0
bottom_depth_success_heading_relax_cap_deg = 3.0
```

效果：上一轮实车末端 `y≈2.41cm、heading≈5.74°` 不再算成功；控制器会继续尝试再倒深约 `1cm`，并把最终角度压到 `3°` 以内。
