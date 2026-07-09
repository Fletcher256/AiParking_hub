# 自动泊车完整推进计划（Codex 执行版）- 2026-06-12

> 本文档是面向 Codex 的**执行规格书**。目标唯一：在现有硬件与系统框架下，用 YOLO 视觉识别 + STM32 闭环控制实现小车自动泊车。
> 所有文件路径、CLI 参数、验收数值都是约定，Codex 实施时不得擅自更改既有约定（尤其是安全门与已验证链路）。

---

## 0. 不可触碰的前提（先读）

以下内容**已验证可用，禁止重新配置或"顺手优化"**：

- 摄像头/YOLO 链路：`/opt/sample/parking_yolo_seg_safe/`，输出车位检测 JSON 到 `UDP 127.0.0.1:24580`。
- dToF 配置（见 `docs/dtof_chn0_breakthrough_20260603.md`）——本计划不使用 dToF，不要动它。
- STM32 链路：`/dev/ttyUSB0`，9600 8N1，V2 协议 `@seq` 前缀，命令集 `PING / MOVE / ARC / STOP / SERVO / PWM_STAT / STAT`。舵机 `STE=90` 为中位（PULSE=1500），`STE=60 → PULSE=1333`，`STE=120 → 约1667`。
- 板端控制器：`/opt/parking/autopark/board_parking_controller.py`，**纯 Python 标准库**（板上没有 pip 包），解释器 `/usr/local/bin/python3`。
- PC 侧执行入口：`D:\parking_board_agent`，venv 解释器 `.venv\Scripts\python`，板端命令通过 `tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina ...` 下发。
- 坐标语义：**后置摄像头，泊车 = 倒车入位**；上游报文里 `+x_cm` 实际是倒车方向（历史误标 forward，不要被字段名骗）。

安全门（一条都不能删，新代码必须全部继承）：

```text
没有 --arm                      -> 不允许运动
没有 /tmp/parking_armed         -> 不允许运动
dry-run                        -> 永远不发送运动命令
YOLO 丢失 > 0.5 s               -> STOP
线框余量过小 (line_risk)        -> STOP
状态发散                        -> STOP
STM32 状态异常 (ACK/DONE/STAT)  -> STOP
总运动距离超上限                -> STOP
进程异常退出路径                -> 尝试发 STOP
实车测试必须从单步动作开始
```

---

## 1. 目标重定义与能力阶梯

"任意位置自动泊车"不是一步到位的目标，拆成能力等级。每级是上一级的超集，**逐级验收，不跳级**。

| 等级 | 初始位姿范围 | 需要的新能力 | 状态 |
|---|---|---|---|
| L0 | 固定标定位姿（±2cm / ±2°） | 单步动作响应标定 | **当前所在级** |
| L1 | 横向 ±5cm，航向 ±5°，车位全可见 | 每步重规划（仅倒车动作）自动连续执行 | 短期目标（本计划主体） |
| L2 | 横向 ±15cm，航向 ±10° | 前进修正动作 + 阶段状态机 | 中期目标 |
| L3 | 车位局部可见（只看到入口边） | 局部可见状态估计 + 入库末段盲走策略 | 中期偏后 |
| L4 | 车位初始不可见，需要先寻找 | 搜索行为 / 记忆建图 | 远期，本计划不承诺 |

**当前硬件明确不支持/不承诺**：动态障碍物避让、非标定地面材质泛化、平行侧方位泊车（本项目是垂直倒车入位）、厘米级绝对定位精度承诺、L4。

成功泊车的**数值定义**（写入新配置 `configs/parking_success_criteria.json`，控制器据此判 done）：

```json
{
  "schema": "parking_success_criteria.v1",
  "done": {
    "slot_x_err_px_abs_max": 15,
    "slot_heading_err_deg_abs_max": 4.0,
    "slot_y_dist_cm_max": 10.0,
    "min_margin_px_min": 60,
    "required_stable_frames": 3
  },
  "abort": {
    "min_margin_px_floor": 40,
    "vision_lost_sec": 0.5,
    "max_total_cm": 60,
    "max_steps": 12,
    "divergence_x_err_px": 200
  }
}
```

（数值是初始值，标定后允许在文档中记录理由后调整；`done` 判定满足时控制器发 `STOP`、写 `verdict=parked`、正常退出。）

---

## 2. 系统架构（七层，各层归属文件）

```text
[感知层]      /opt/sample/parking_yolo_seg_safe  -> UDP 127.0.0.1:24580 JSON (polygon)
[状态估计层]  board_parking_controller.py :: slot_relative_state()      (已完成, 阶段1)
[响应模型层]  configs/parking_action_response_model.json + 更新工具      (阶段2雏形, 本计划补全)
[规划层]      动作库 configs/parking_action_library.json + 在线评分选择   (本计划核心新增)
[执行层]      STM32 V2 串口命令 (ARC/MOVE/STOP), 每次只执行一个短动作     (已验证)
[安全监督层]  上述安全门, 嵌在控制器主循环, 优先级高于规划层              (已有, 继承)
[日志回归层]  JSONL 事件流 + PC 侧 analyzer/replay 工具                  (已有雏形, 本计划扩展)
```

各层风险一句话：感知层=多边形抖动与丢失；状态层=homography 误差导致 cm 值不可信（所以规划以 px 指标为主、cm 为辅）；响应模型层=样本少导致预测错向；规划层=动作抖动/重复选错动作；执行层=命令距离与实际距离不一致；安全层=门太松压线、太紧寸步难行；日志层=字段缺失导致事后无法归因。

## 3. 算法路线裁决（一次性定论，不再反复）

**主路线 = 动作模板库 + 每步重规划（relative-pose + action-template replanning）。** 理由：

1. 已有失败经验证明固定走廊控制/固定分段倒车在本车上压线（响应模型不准，不是舵机没发）。
2. 每步停车重新观察，把"模型不准"的伤害限制在一个 ≤6cm 的短动作内，配合安全门天然安全。
3. 动作库有限（5~8 个），响应可以用少量实测样本标定，不需要精确运动学模型。
4. Reeds-Shepp / Hybrid A* 需要可靠的连续位姿估计与准确转弯半径，当前两者都没有；**升级条件**：当响应模型对每个动作有 ≥5 个实测样本、且由实测拟合出稳定等效转弯半径后，才值得把动作序列搜索升级为 Reeds-Shepp 简化版。强化学习不在本计划范围（样本成本不可接受）。
5. 固定分段倒车降级为 fallback：仅当起始位姿落在 L0 标定窝内时允许作为兜底。

每步循环（控制器 `--strategy action_replanner` 的主循环）：

```text
读稳定状态(stable_frames>=3) -> 安全门检查 -> 枚举动作库 -> 用响应模型预测下一状态
-> 评分 -> 选最优 -> (实车模式)执行该动作 -> 等 DONE+车停稳 -> 重新观察 -> 重复
直到 done 判定 / 任一 abort 门触发
```

---

## 4. 状态向量（基于已实现的 slot_relative_state）

已有字段（阶段1已验证，dry-run 抖动：x_err stdev 0.54px、heading 0.18°、lateral 0.052cm、pose_quality 0.938）：

```text
corridor.slot_x_err_px / slot_entry_x_err_px / left_margin_px / right_margin_px / min_margin_px / line_risk
image.slot_heading_err_deg / closeness
ground_estimate.slot_y_dist_cm / slot_lateral_cm
confidence / stable_frames / pose_quality / phase_hint
gates.stable_enough / line_margin_ok / heading_ok / lateral_ok
```

**本计划要求补充的字段**（任务 T3 实现，全部可从现有 polygon 推导，纯标准库）：

| 新字段 | 含义 | 用途 |
|---|---|---|
| `image.slot_visible_ratio` | polygon 面积 / 近期最大面积的滑窗比值 | 判断车位是否正在离开视野（入库末段） |
| `image.entry_edge_visible` | 入口边两端点是否都在画面内（含边距 10px） | L3 局部可见的先决信号 |
| `vision.lost_ms` | 距上一帧有效检测的毫秒数 | 0.5s STOP 门的显式输入 |
| `vision.seq` / `vision.ts` | 报文序号与时间戳 | 回放对齐、丢帧统计 |
| `motion.last_action_id` / `motion.steps_done` / `motion.total_cm` | 运动记账 | 总距离上限门、抖动抑制 |
| `sanity.delta_consistent` | 上一动作的实测 delta 与响应模型预测同号 | 发散检测：连续 2 次异号 -> STOP |

视觉丢失处理策略（分相位）：`approach_entry / align_in_corridor` 阶段丢失 >0.5s 一律 STOP；`final_straight`（见 §8 相位机）允许按"盲走末段"规则继续。2026-06-13 已在控制器中实现一次性 token 门控版本：只有最近一次稳定、近中线、线边安全的 `action_replanner` 可见动作成功后，才允许在终段盲区消费 `/tmp/parking_final_blind_token.json` 执行一条短距离直线 `MOVE`，随后立即 `STOP` 并标记 token consumed。该能力不是连续 dead-reckon，旧的 `--allow-dead-reckon-after-loss` 仍默认关闭。

---

## 5. 动作模板库（目标形态）

现有 5 个动作保留。**本计划最终动作库**（`configs/parking_action_library.json` 逐步扩到如下，扩充时机标在备注）：

| id | command | 适用 phase | 风险 | 加入时机 |
|---|---|---|---|---|
| reverse_straight_6 | `MOVE D=-6.0 V=1` | 全部倒车相位 | 低 | 已有 |
| reverse_left_hard_6 | `ARC D=-6.0 STE=60 V=1` | approach/align | 已实测从标定位姿变差 | 已有 |
| reverse_left_soft_6 | `ARC D=-6.0 STE=75 V=1` | approach/align | 未标定 | 已有 |
| reverse_right_soft_6 | `ARC D=-6.0 STE=105 V=1` | approach/align | 未标定 | 已有 |
| reverse_right_hard_6 | `ARC D=-6.0 STE=120 V=1` | approach/align | 未标定，**下一个标定对象** | 已有 |
| reverse_straight_12 | `MOVE D=-12.0 V=1` | align（对正后加速进度用） | 距离加倍 | M1 后按 §6 推广规则加入 |
| counter_steer_6 | 动态：与上一弧反向的 `ARC D=-6.0 STE=±` | straighten_or_enter | 反打摆正 | M3 |
| forward_correct_4 | `MOVE D=+4.0 V=1` | recover_forward | **前方无感知，纯里程** | M5（L2 能力），距离硬上限 4cm，连续次数 ≤2 |
| forward_arc_l/r_4 | `ARC D=+4.0 STE=75/105 V=1` | recover_forward | 同上 | M5 |
| stop_wait | `STOP` | 任意 | 无 | 控制器内建，不进库 |

每个动作条目必须含（已有 schema 不变）：`command / kind / distance_cm / servo / allowed_phases / prior_delta / prior_confidence / notes`。新增字段：`max_promote_cm`（该动作允许推广到的最大单步距离，初始全部 6，按标定结果改）、`requires_measured: true|false`（见 §7 硬规则）。

---

## 6. 动作响应标定方案（M1，实车，人在场）

### 6.1 标定协议（每个动作重复执行）

1. **位姿复位**：地面用胶带标出四轮位置框（一次性贴好，拍照存 `artifacts/autopark_baseline/pose_jig_photo_20260612.jpg`）。每次标定前把车摆回框内，dry-run 读 10 帧确认初始状态落在窗口内：`|slot_x_err_px - 基准| < 5px` 且 `|heading - 基准| < 1°`，不满足就重摆。
2. **前置记录**：取 10 个稳定帧的均值作为 `pre_state`（现有 `--stable-frames 3` 之上，分析器侧取均值）。
3. **执行**：一次只执行一个动作，用现有 `--strategy primitive_probe`（命令模板见 §6.4），`--max-motion-steps 1 --max-total-cm 8`。
4. **后置记录**：等 DONE + `--settle-sec 0.5` 后再取 10 个稳定帧均值作为 `post_state`。
5. **判定显著性**（基于已测噪声 3σ）：`|Δslot_x_err_px| > 3px`、`|Δheading| > 0.6°`、`|Δslot_lateral_cm| > 0.2cm`、`|Δmin_margin_px| > 2px` 才算真实变化，否则记 `neutral`。
6. **verdict 规则**：`improved` = |x_err| 与 |lateral| 同时减小且 min_margin 不降超过 5px；`worsened` = 任一显著变差；其余 `mixed/neutral`。
7. **样本量**：每个动作**同一位姿至少 3 次**。SNR 很高（预期 delta ~28px vs 噪声 0.5px），3 次足以定方向，方向确认后再补 2 次定均值。两次结果方向相反 → 检查复位质量，重测。

### 6.2 标定顺序（明确回答"是否先测 STE=120"：**是**）

```text
1. ARC D=-6.0 STE=120 V=1   (评分器当前推荐；与已测失败的 STE=60 对称假设)
2. ARC D=-6.0 STE=105 V=1
3. MOVE D=-6.0 V=1          (基线，校验 D=-6 实际位移多少 cm)
4. ARC D=-6.0 STE=75 V=1
5. (STE=60 已有 1 个样本，补 2 次确认即可，排最后)
```

### 6.3 推广到 12cm / 20cm 的规则

某动作 6cm 版满足：≥2/3 样本 `improved`、且用响应模型线性外推 2 倍距离后预测 `min_margin_px` 仍 >60 → 允许做**一次** 12cm 探针。实测 delta 与 2× 线性预测偏差 <35% → 接受线性缩放，`max_promote_cm=12`；否则保持 6cm。20cm 同理基于 12cm，且仅限 `reverse_straight`。

### 6.4 探针命令模板（PC 侧，PowerShell，已验证可用的形式）

```powershell
.venv\Scripts\python tools\board_auto_ssh.py run --host 192.168.137.2 --user root --password ebaina --command-timeout 60 --allow-risk "/usr/local/bin/python3 /opt/parking/autopark/board_parking_controller.py --strategy primitive_probe --primitive-command 'ARC D=-6.0 STE=120 V=1' --primitive-max-command-abs-d-cm 8 --arm --target-wait-sec 1 --settle-sec 0.5 --move-read-sec 8 --stable-frames 3 --pixel-vision-lost-stop-sec 0.5 --max-motion-steps 1 --max-total-cm 8 --log-stm32-detail --pre-steer-settle-sec 0.5 --log-jsonl /tmp/parking_probe_ste120_r1_20260612.jsonl"
```

每次跑完取回日志到 `artifacts\autopark_baseline\`，文件名带动作、轮次、日期。

### 6.5 响应模型更新（新工具，任务 T2）

`configs/parking_action_response_model.json` 升级为**按状态桶存样本**：

```json
{
  "schema": "parking_action_response_model.v2",
  "noise_3sigma": {"slot_x_err_px": 3.0, "slot_heading_err_deg": 0.6, "slot_lateral_cm": 0.2, "min_margin_px": 2.0},
  "records": [
    {
      "action_id": "reverse_right_hard_6",
      "bucket": {"phase": "approach_entry", "x_err_sign": "+", "x_err_bin": "40-120", "heading_bin": "-8-0"},
      "samples": [
        {"date": "2026-06-12", "log": "parking_probe_ste120_r1_20260612.jsonl",
         "pre": {"slot_x_err_px": 76.3, "slot_heading_err_deg": -3.5, "slot_lateral_cm": -3.9, "min_margin_px": 93.1, "slot_y_dist_cm": 48.3},
         "post": {}, "delta": {}, "verdict": ""}
      ],
      "mean_delta": {}, "n": 1, "confidence": 0.33
    }
  ]
}
```

置信度公式：`confidence = n / (n + 2)`（1 样本 0.33，3 样本 0.6，5 样本 0.71）。桶的划分：`phase × sign(slot_x_err_px) × |x_err| 三档(0-40/40-120/120+) × heading 三档`。评分器查询时先找同桶 measured，找不到降级用邻桶（confidence ×0.5），再找不到用 prior。

---

## 7. 一步重规划器（M2 软件核心，任务 T3）

### 7.1 评分函数（沿用动作库 scoring 段，权重已存在，公式写死如下）

```text
score(a) = - w_x   * |pred.slot_x_err_px|
           - w_h   * |pred.slot_heading_err_deg|
           - w_lat * |pred.slot_lateral_cm|
           - w_m   * max(0, margin_target - pred.min_margin_px)
           + w_p   * progress(pred.slot_y_dist_cm 的有效减少量)
           - 1000  * line_risk(pred)                # 事实硬约束
           - w_ph  * phase_mismatch
           - w_lc  * (1 - confidence(a, bucket))
           - w_unc * uncalibrated(a)
           - w_st  * |servo - 90| / 30
           - w_sw  * switch_penalty(a, last_action)  # 新增, 见 7.2
```

硬约束（直接淘汰，不参与排名）：预测 `min_margin_px < abort.floor(40)`；预测 `line_risk` 触发；`phase` 不在 `allowed_phases`；**实车模式下 `requires_measured=true` 而该动作在当前桶无 measured 记录或 verdict=worsened**（→ 未标定动作永远不会被实车自动执行，只能走 primitive_probe 标定，这是回答"如何处理未标定动作"的硬规则）。

### 7.2 抗抖动与抗"重复选错"

- **换向惩罚**：`switch_penalty = w_sw(初始 5.0)`，若候选与上一步动作的舵向相反则计入；同向或直行不罚。
- **保持滞回**：上一步动作若仍合法且分数与新最优差 < ε(初始 3.0)，继续保持上一步动作。
- **连败熔断**：同一动作连续 2 次实测 `worsened`（`sanity.delta_consistent` 连续异号同理）→ 本次泊车内禁用该动作并发 STOP，等待人工；这是"避免一直选同一个错误动作"的机制。
- **进度看门狗**：连续 3 步 `slot_y_dist_cm` 减少量 < 1cm 且 |x_err| 无改善 → STOP，verdict=`stalled`。

### 7.3 实现位置与模式

全部逻辑写进 `tools/board_parking_controller.py`（单文件、纯标准库，上传板端覆盖 `/opt/parking/autopark/`），新增：

```text
--strategy action_replanner
--replanner-dry-run            # 只打分记录, 永不发运动命令(即使有 --arm)
--confirm-each-step            # 每步打印推荐动作, 等 stdin 'y' 才执行(M3 用)
--action-library-json PATH     # 板端路径 /opt/parking/autopark/parking_action_library.json
--response-model-json PATH
--success-criteria-json PATH
--max-steps N
```

JSONL 每步事件 schema（日志回归层的核心，字段缺一不可）：

```json
{"ts": 0, "event": "replanner_step", "step": 1,
 "pre_state": {}, "ranking": [{"id": "", "score": 0.0, "origin": "measured|prior", "hard_blocked": false}],
 "chosen": {"id": "", "command": "", "reason": "best|hold_hysteresis|none_eligible"},
 "gates": {"motion_gate_open": false, "will_execute_motion": false, "cap_would_stop": false, "lateral_would_stop": false},
 "stm32": {"sent": "", "ack": "", "done": "", "pwm_stat": "", "stat_after": ""},
 "post_state": {}, "delta": {}, "verdict": "improved|worsened|neutral|mixed|unknown",
 "totals": {"steps_done": 1, "total_cm": 6.0}}
```

### 7.4 回放验证（任务 T4，实车前必过）

新工具 `tools/parking_replay_planner.py`（PC 侧）：把历史 slot-state JSONL 逐行喂给与板端**同一份**评分代码（import 同模块，禁止复制粘贴两份逻辑），输出每行的 ranking 与 chosen。验收：

- 对 `parking_slot_state_dryrun_20260612.jsonl` 33 行，chosen 动作切换次数 ≤2（状态静止时推荐必须稳定）；
- 人工 review：在 `x_err=+76px`（车位偏右）场景下 chosen 的舵向必须是"向右修正"一侧，方向错了就是评分/符号 bug，必须修完才许实车。

---

## 8. 相位状态机（M3 起生效）

```text
approach_entry        slot_y_dist_cm > 25
align_in_corridor     10 < slot_y_dist_cm <= 25
straighten_or_enter   slot_y_dist_cm <= 10 且 |heading| > 4°   -> 允许 counter_steer
final_straight        slot_y_dist_cm <= 10 且 |heading| <= 4°  -> 只允许 reverse_straight
recover_forward       任意相位下 min_margin < 55px 或 x_err 越改越大  -> 只允许 forward_* (M5 才启用)
done                  success_criteria 满足
```

相位切换加 2cm/1° 滞回防振荡。`phase_hint` 已在阶段1输出，本节是把 hint 升级为带滞回的正式状态机（任务 T3 内完成）。

---

## 9. 实车测试阶梯（每级有通过标准与停止条件，不许跳级）

| 级 | 内容 | 通过标准 | 停止条件 |
|---|---|---|---|
| S1 dry-run | `action_replanner --replanner-dry-run` 板上跑 60s | 推荐稳定（切换≤2 次）、无异常、日志字段齐全 | 任何异常输出 |
| S2 单步标定 | §6 标定 campaign | 5 动作各 ≥3 样本入响应模型 | 两次方向相反 |
| S3 人审单步 | `--confirm-each-step --max-steps 1` | 连续 5 次推荐被人判合理且执行后 verdict≠worsened | 1 次 worsened 即回 S2 查模型 |
| S4 两步连续 | `--max-steps 2 --max-total-cm 14` | 3 回合无门触发、x_err 单调改善 | 任一门触发 |
| S5 多步自动 | `--max-steps 8 --max-total-cm 50`，从 L0 位姿到 done | 3/5 回合达 done 判定 | margin<40 / stalled / 发散 |
| S6 近完整泊车 | L1 范围内随机摆 5 个起点 | 4/5 成功 | 同上 |
| S7 扩范围 | L2 网格(横向±15cm×航向±10°, 9 个点) | 记录成功矩阵, 不设硬标准, 输出能力边界报告 | 同上 |

每级实车都遵守：先 `PING`+`STAT` 确认 STM32 正常、`PWM_STAT` 确认舵机、`/tmp/parking_armed` 由人手动创建、跑完手动删除。

---

## 10. YOLO 模型升级回归（升级前后各跑一次，工具已有雏形 `tools/parking_model_regression_compare.py`）

- **升级前冻结基准**：当前模型文件 md5、`artifacts/autopark_baseline/` 下全部 slot-state 日志、固定场景 dry-run 60s 日志一份（命名 `slot_state_baseline_model_vX.jsonl`）。
- **升级后比较**（同一物理场景重跑 60s dry-run）：① polygon 与基准的 IoU 均值 >0.85；② `slot_x_err_px / heading / lateral` 均值漂移 < 各自 3σ 噪声的 3 倍；③ **符号检查（最高优先）**：把车摆到明确偏左/偏右两个位姿，确认 `slot_x_err_px` 符号与旧模型一致——符号翻转会直接导致动作方向反，必须人工确认后才许接控制器；④ stdev 不得超过旧模型 3 倍。
- 任一项不过 → 回滚旧模型，控制器不感知升级。响应模型按状态桶存储，只要状态语义不变就无需重标。

---

## 11. Codex 任务清单（按优先级，含验收）

> 通用约束：板端代码纯标准库；上传后必须 `py_compile` 验证；每个任务完成后更新对应 docs；PC 侧统一用 `.venv\Scripts\python`；不创建 git 仓库不代表不留痕——所有结论写 docs + artifacts。

**T1（P0，半天）成功判据与门配置**
新建 `configs/parking_success_criteria.json`（§1 内容）；`board_parking_controller.py` 读取它并实现 done/abort 判定与 `verdict=parked|stalled|aborted` 退出码。验收：dry-run 下人为喂满足 done 的状态行，控制器正确判 parked 且不发任何运动命令。

[done 2026-06-12, 见 `docs/autopark_t1_success_criteria_20260612.md`]

**T2（P0，半天）响应模型 v2 + 更新工具**
`tools/parking_response_model_updater.py`：输入 1 个 probe JSONL → 提取 pre/post 10 帧均值、算 delta、按 §6.1 规则判 verdict、写入 v2 模型（含桶、confidence 公式）。迁移现有 STE=60 样本到 v2。验收：对已有 `parking_probe_left_20260612.jsonl` 重算，delta 与状态报告中数值一致（x_err +28、lateral -1.67、margin -24）。

[done 2026-06-12, 见 `docs/autopark_t2_response_model_v2_20260612.md`]

**T3（P0，1 天）action_replanner 策略 + 状态字段补全 + 相位机**
按 §4 新字段、§7 评分与硬规则、§8 相位机扩展 `board_parking_controller.py`；新增 CLI 旗标见 §7.3。评分逻辑放独立可 import 的纯函数区（同文件内 `# ===== planner core =====` 段），供 T4 复用。验收：板上 S1 dry-run 通过。

[done 2026-06-12, 见 `docs/autopark_t3_action_replanner_20260612.md`；本地 py_compile、T4 回放、函数级 smoke test 与板端 S1 no-motion dry-run 均通过；S1 日志见 `artifacts/autopark_baseline/parking_action_replanner_dryrun_20260612.jsonl`]

**T4（P0，半天）回放规划器**
`tools/parking_replay_planner.py` 按 §7.4。验收：33 行回放切换 ≤2 次 + 方向人工 review 通过。

[done 2026-06-12, 见 `docs/autopark_t4_replay_planner_20260612.md`；输出 `artifacts/autopark_baseline/parking_replay_planner_20260612.json` 与 `.csv`，33 行回放通过，稳定动作切换 0 次，方向 review 通过]

**T5（P1，半天）标定 campaign 自动化**
`tools/parking_probe_runner.py`：串起"提示人工复位 → 复位质量检查（dry-run 10 帧比对基准窗口）→ 下发 probe → 取回日志 → 调 T2 更新模型 → 打印 verdict"。验收：跑通一次 STE=120 全流程，模型文件出现新 measured 记录。

[software implemented 2026-06-12, 见 `docs/autopark_t5_probe_runner_20260612.md`；本地 py_compile 与 plan-only smoke test 通过；两次 `STE=120` 执行尝试均因 reset_quality_failed 被拦截，未动车、未新增 measured 样本；r2 的 `slot_x_err_px` 从基准 70.621 偏到 15.481，需先复位到同一初始位姿]

**T6（P1，与 T5 并行的实车工作）执行 §6.2 标定顺序**
产出：5 动作 ≥3 样本的响应模型 + `docs/autopark_calibration_report_2026061X.md`（每动作 mean_delta、verdict、是否推广 12cm 的决定）。

**T7（P1，半天）S3–S5 实车阶梯执行**
按 §9 逐级跑，每级产出一段 docs 记录 + artifacts 日志。

**T8（P2，1 天）前进修正动作（L2 能力）**
动作库加 `forward_correct_4 / forward_arc_*_4` 与 `recover_forward` 相位；前进时无感知，硬上限 4cm、连续 ≤2 次、累计前进 ≤12cm。先标定（前进版 §6 协议）再入库。验收：构造 margin 临界场景，控制器选择前进修正且回到倒车相位。

**T9（P2，半天）两步 lookahead**
仅当 5 动作桶内 confidence ≥0.6 后做：评分器递归预测 2 步（链式叠加 mean_delta），仍只执行第 1 步。加开关 `--lookahead 2`，默认 1。验收：回放中 lookahead=2 与 1 的 chosen 差异有日志可查，且不出现抖动恶化。

**T10（P3）YOLO 升级回归流程落地**（§10，等用户真的换模型时执行）。

---

## 12. 风险清单与缓解

| 风险 | 缓解 |
|---|---|
| YOLO polygon 抖动/误检 | stable_frames≥3 + 10 帧均值 + 3σ 显著性判定；pose_quality<0.8 不规划 |
| 贴边状态被一刀切 STOP | `min_margin<30` 硬停；`30<=min_margin<40` 进入 edge recovery，只允许预测增大边距且降低横向误差的动作 |
| homography 不准（cm 不可信） | 评分以 px 指标为主，cm 只用于 progress 项；done 判定 px 与 cm 双条件 |
| 舵机死区/响应慢 | 已有 `--pre-steer-settle-sec 0.5` 先打舵后走；PWM_STAT 核对 CCR 实际值 |
| 命令 D 与实际位移不一致 | MOVE D=-6 标定时同时记录视觉测得实际位移，存入响应模型，规划用实测值 |
| 车位丢失 | 0.5s STOP 门 + `slot_visible_ratio` 预警（<0.6 时禁选大弧动作） |
| 压线 | margin 硬约束 40px 淘汰 + 55px 进 recover_forward + 1000 权重 line_risk |
| 初始位姿超能力 | 起步时 x_err/heading 超 L 级范围 → 拒绝启动并打印当前能力等级 |
| 模型升级状态跳变 | §10 符号检查 + 回滚机制 |
| 板端性能不足 | 规划是 5~8 动作的算术评分，单步 <1ms，无风险；JSONL 写 /tmp 防 flash 磨损 |
| 连败/振荡 | §7.2 熔断 + 滞回 + 进度看门狗 |

---

## 13. 路线图与当前最关心问题的直接回答

**路线图**：1 天内 = T1+T2+T4 软件 + STE=120 首次标定（拿到第 2 个 measured 样本）；2–3 天 = T3 dry-run 通过 + 5 动作标定完（S1/S2 完成）；1 周 = S3→S5，从 L0 位姿完成首次全自动倒车入位；其后 = T8 前进修正 + S6/S7 把范围推到 L2，再评估 Reeds-Shepp 升级。

**五个问题的结论**：

1. **路线正确**。"动作模板库 + 每步重规划"是当前感知/执行精度下唯一既安全又可标定的路线，本计划予以确认并细化为可执行规格。
2. **从阶段 2 到实车泊车的路径** = 本文 §6 标定 → §7 规划器 → §9 阶梯，对应任务 T1–T7，约一周。
3. **应该先测 STE=120**。它是评分器推荐、与已测失败 STE=60 的对称假设，单个样本即可确认右弧方向性；按 §6.3 规则决定是否推广 12cm。
4. **能扩展初始范围的规划器** = 按状态桶存储的响应模型（同一动作在不同位姿有不同 delta）+ 相位状态机 + 前进修正动作；范围扩展本质是"桶覆盖率"问题，靠 S7 成功矩阵逐步填。
5. **离"任意位置"还缺**：局部可见状态估计（L3）、入库末段盲走策略（L3）、车位搜索行为（L4）、以及把动作序列搜索升级为 Reeds-Shepp 的实测转弯半径模型。前两者在 L2 验收后启动，后两者远期。

---

*文档维护规则：每完成一个 T 任务，在本文件对应条目后追加 `[done YYYY-MM-DD, 见 docs/xxx.md]`，并同步 `docs/autopark_long_term_memory.md`。*
