# AI 复刻用：倒车泊车主逻辑交接说明（2026-06-27）

本文档用于把当前工程的**倒车泊车主算法逻辑**交给另一个 AI/工程师，使其可以在不依赖完整 SDK 的情况下，几乎复刻同等决策逻辑并移植到另一套小车运行环境。

重点：本文档描述的是**主控制逻辑**，不是海思板 MPP/YOLO/NPU 编译链，也不是具体串口驱动实现。

---

## 0. 你要复刻的核心目标

当前泊车逻辑不是固定脚本，而是一个 stepwise replanner：

```text
停车位分割 polygon
-> 稳定的车位相对状态 slot_relative_state
-> 有界动作库 action_library
-> 用 response_model 预测每个动作后的状态
-> 计算 cost，选一个短动作
-> 安全门判断
-> 只执行一个动作
-> 停车，重新观察，重新规划
```

最核心的一句话：

```text
每次只执行一个短倒车动作，然后停止观察再规划。
```

---

## 1. 必读文件

如果你只想理解和复刻主算法，按顺序阅读：

```text
docs/current_reverse_parking_logic_20260627.md
configs/parking_action_library.json
configs/parking_action_response_model.json
configs/parking_success_criteria.json
configs/perception_filter.json
configs/chassis_kinematics.json
configs/chassis_signs.json
tools/board_parking_controller.py
tools/parking_action_scorer.py
```

主入口代码：

```text
tools/board_parking_controller.py
```

最重要函数：

```text
slot_infos_from_udp()
slot_pixel_geometry()
assess_slot_completeness()
SlotStabilityFilter
slot_relative_state()
action_replanner_command_from_state()
planner_score_actions()
planner_predicted_state()
planner_cost_state()
evaluate_parking_criteria()
send_motion()
```

---

## 2. 外部输入契约

算法只需要一个“停车位检测结果流”，不强依赖当前海思 YOLO 实现。

每帧输入应能提供：

```json
{
  "image_size": [640, 640],
  "detections": [
    {
      "class_name": "Parking",
      "confidence": 0.61,
      "bbox_xyxy": [116, 167, 505, 560],
      "mask_polygon": [[118,274],[122,238],...],
      "mask_area_px": 120656
    }
  ],
  "detection_count": 1
}
```

必须字段：

```text
class_name / label
confidence
mask_polygon
image_size
```

可选但建议：

```text
bbox_xyxy
mask_area_px
center_px
```

如果目标平台不是 UDP 输入，可以直接把检测结果作为 Python dict / C++ struct / ROS msg 喂给 `slot_infos_from_udp()` 等价逻辑。

---

## 3. 状态表示：slot_relative_state

复刻时应先实现一个统一状态结构：

```json
{
  "stable": true,
  "stable_enough": true,
  "confidence": 0.62,
  "pose_quality": 0.81,
  "phase_hint": "align_in_corridor",

  "slot_x_err_px": 68.4,
  "slot_entry_x_err_px": 57.5,
  "slot_heading_err_deg": -16.6,
  "slot_y_dist_cm": 40.5,
  "slot_lateral_cm": -5.0,

  "left_margin_px": 176.0,
  "right_margin_px": 312.8,
  "min_margin_px": 176.0,
  "line_risk": false,
  "closeness": 0.96,

  "stable_frames": 5,
  "required_stable_frames": 5,

  "slot_visible_ratio": 0.31,
  "entry_edge_visible": true,
  "slot_completeness_status": "suspect",
  "slot_completeness_can_refresh_geometry": false,
  "slot_completeness_reasons": ["angle_not_rectangular", "opposite_width_mismatch"]
}
```

其中最影响动作选择的是：

```text
slot_x_err_px
slot_heading_err_deg
slot_lateral_cm
slot_y_dist_cm
min_margin_px
line_risk
stable_enough
slot_completeness_can_refresh_geometry
```

---

## 4. 稳定过滤

不要用单帧检测直接控制小车。

当前过滤策略：

```text
required_frames = 5
center shift gate = 4cm
yaw shift gate = 8deg
static gate scale = 0.5
```

简化实现：

```python
class StabilityFilter:
    def __init__(self):
        self.samples = []

    def add(info):
        if samples is empty:
            append
            return unstable
        compare new center/yaw with previous or fused state
        if jump too large:
            reject as outlier
        else:
            append
            keep latest 5
        return stable if len(samples) >= 5
```

必须原则：

```text
连续 5 帧基本一致后才允许动作规划。
动作后必须清空/重置稳定过滤，再重新观察。
```

---

## 5. 成功/终止条件

来自：

```text
configs/parking_success_criteria.json
```

认为已经停好：

```text
abs(slot_x_err_px) <= 15
abs(slot_heading_err_deg) <= 4.0
slot_y_dist_cm <= 10.0
min_margin_px >= 60
stable_frames >= 3
line_risk == false
```

必须停止/中止：

```text
min_margin_px < 40
vision lost >= 0.5s
max_total_cm > 60
max_steps > 12
line_risk == true
lateral divergence confirmed
```

实车早期调试建议更严格：

```text
max_steps = 1
max_total_cm = 单步动作上限
```

---

## 6. 动作库

当前动作库在：

```text
configs/parking_action_library.json
```

复刻时至少要支持这些动作：

```text
reverse_straight_6     ARC D=-6.0 STE=100 V=1
reverse_straight_4     ARC D=-4.0 STE=100 V=1
reverse_left_hard_6    ARC D=-6.0 STE=60  V=1
reverse_left_hard_4    ARC D=-4.0 STE=60  V=1
reverse_left_hard_3    ARC D=-3.0 STE=60  V=1
reverse_left_soft_6    ARC D=-6.0 STE=75  V=1
reverse_right_soft_6   ARC D=-6.0 STE=105 V=1
reverse_right_hard_6   ARC D=-6.0 STE=120 V=1
reverse_right_hard_4   ARC D=-4.0 STE=120 V=1
reverse_right_hard_3   ARC D=-3.0 STE=120 V=1
```

约定：

```text
D < 0      表示倒车
STE = 100 近似直退
STE < 100 左弧
STE > 100 右弧
```

注意：如果你的底盘舵机方向不同，必须重新标定 STE 左右关系。

---

## 7. 响应模型

响应模型在：

```text
configs/parking_action_response_model.json
```

每条记录表达：

```text
在某个状态 bucket 下，执行某个 action 后，slot_relative_state 大致怎么变化。
```

bucket 维度：

```text
phase
x_err_sign
x_err_bin
heading_bin
```

典型记录包含：

```json
{
  "action_id": "reverse_right_hard_6",
  "command": "ARC D=-6.0 STE=120 V=1",
  "bucket": {
    "phase": "straighten_or_enter",
    "x_err_sign": "+",
    "x_err_bin": "0-40",
    "heading_bin": "-8-0"
  },
  "mean_delta": {
    "slot_y_dist_cm": -1.48,
    "slot_x_err_px": -33.79,
    "slot_lateral_cm": 2.16,
    "slot_heading_err_deg": 0.71,
    "min_margin_px": 7.90
  },
  "confidence": 0.6,
  "dominant_verdict": "worsened"
}
```

预测公式：

```python
predicted_state = current_state + mean_delta
```

如果没有精确 bucket：

```text
exact match
-> same phase/sign neighbor
-> action-only neighbor
-> prior_delta
```

越往后置信度越低。

---

## 8. 动作打分

每个候选动作都预测一个 post_state，然后计算 cost。

核心 cost 维度：

```text
abs(pred.slot_x_err_px)
abs(pred.slot_heading_err_deg)
abs(pred.slot_lateral_cm)
progress bonus, 即 slot_y_dist_cm 减小是好事
min_margin_px 不足惩罚
line_risk 极大惩罚
phase mismatch 惩罚
low confidence 惩罚
uncalibrated 惩罚
large steer 惩罚
```

伪代码：

```python
best = None
for action in action_library:
    if action not allowed in current phase:
        continue

    response = find_response_model(action, current_state_bucket)
    if real_motion and action.requires_measured and response.is_prior_only:
        hard_block(action, "requires_measured")
        continue

    pred = predict(current_state, response.mean_delta or action.prior_delta)

    if pred.line_risk or pred.min_margin_px < floor:
        hard_block(action, "predicted_line_risk")
        continue

    if action moves lateral in obviously wrong direction:
        hard_block(action, "wrong_lateral_correction_direction")
        continue

    cost = (
        W_X * abs(pred.slot_x_err_px)
        + W_HEAD * abs(pred.slot_heading_err_deg)
        + W_LAT * abs(pred.slot_lateral_cm)
        - W_PROGRESS * progress
        + W_MARGIN * margin_shortfall
        + W_LOW_CONF * (1 - response.confidence)
        + W_STEER * large_steer_penalty
    )

    keep lowest cost unblocked action
```

输出只能是：

```text
WAIT
STOP
ARC ...
MOVE ...
```

---

## 9. 安全门

无论哪个 AI/工程如何重写，必须保留以下安全门。

### 9.1 no-motion

以下模式绝对不能写串口运动命令：

```text
dry_run == true
replanner_dry_run == true
```

### 9.2 arm 文件

真实运动必须同时满足：

```text
--arm
/tmp/parking_armed exists
not dry_run
not replanner_dry_run
```

### 9.3 will_execute_motion

只有满足全部条件才允许发动作：

```python
will_execute_motion = (
    armed
    and stable
    and not no_motion
    and action in [MOVE, ARC]
    and not WAIT
    and not STOP
    and not already_aligned
    and not lateral_would_stop
    and not cap_would_stop
)
```

### 9.4 单一出口

所有运动命令必须走同一个函数：

```text
send_motion(cmd)
```

禁止在其他地方直接写串口发送 `MOVE` / `ARC` / `SERVO`。

---

## 10. 当前 2026-06-27 状态下的实际决策例子

输入稳定状态：

```text
slot_y_dist_cm ≈ 40.5
slot_lateral_cm ≈ -5.0
slot_heading_err_deg ≈ -16.6
slot_x_err_px ≈ 68.4
min_margin_px ≈ 176
phase_hint = align_in_corridor
```

当前 replanner 选出：

```text
action_id = reverse_right_hard_6
command = ARC D=-6.0 STE=120 V=1
origin = measured_neighbor
response_match = action_only_neighbor
confidence = 0.15
```

预测变化：

```text
slot_x_err_px:        68.4  -> 34.6
slot_lateral_cm:     -5.0   -> -2.8
slot_heading_err_deg:-16.6  -> -15.9
min_margin_px:       176   -> 184
```

因此它被选择，是因为预计能明显减少横向误差，并且不会压线。

但注意：

```text
confidence = 0.15
```

这意味着它只能作为“单步探测/验证”的候选，不适合直接多步自动泊车。

---

## 11. 当前最建议的算法改进

如果要优化“可能倒不进去”的问题，优先改这三个点。

### 11.1 低置信度降级短动作

建议规则：

```python
if chosen.confidence < 0.30:
    if chosen.command has D=-6.0:
        replace with equivalent D=-3.0 or D=-4.0 action
```

例如：

```text
ARC D=-6.0 STE=120 V=1
```

降级成：

```text
ARC D=-3.0 STE=120 V=1
```

或：

```text
ARC D=-4.0 STE=120 V=1
```

### 11.2 几何 suspect 时禁止大动作

建议规则：

```python
if slot_completeness_can_refresh_geometry is false:
    max_action_distance_cm = 3 or 4
```

### 11.3 实车模式下禁止 action_only_neighbor 的 6cm 大动作

建议规则：

```python
if real_motion and response_match == "action_only_neighbor" and action.distance_cm >= 6:
    hard_block or downgrade
```

---

## 12. 最小复刻版本模块划分

如果从零重写，可以拆成这些文件：

```text
perception_state.py
  - parse_detection()
  - polygon_to_slot_geometry()
  - assess_completeness()
  - make_slot_relative_state()

stability_filter.py
  - SlotStabilityFilter

planner_config.py
  - load action library
  - load response model
  - load success criteria

replanner.py
  - bucket_state()
  - find_response()
  - predict_state()
  - score_action()
  - choose_action()

safety_gate.py
  - evaluate_parking_criteria()
  - will_execute_motion()
  - send_motion() single outlet

runtime_loop.py
  - receive detection
  - update filter
  - choose one action
  - execute or dry-run
  - reset perception after motion
```

---

## 13. 最小运行循环伪代码

```python
while True:
    raw = receive_latest_detection()

    if raw is None:
        if vision_lost_too_long():
            stop()
            break
        continue

    info = detection_to_slot_info(raw)
    stable, stability = filter.add(info)

    if not stable:
        log("WAIT=UNSTABLE")
        continue

    state = make_slot_relative_state(info, stability)
    criteria = evaluate_parking_criteria(state)

    if criteria.verdict == "parked":
        stop()
        break

    if criteria.verdict == "aborted":
        stop()
        break

    action = replanner.choose_action(state)

    if action in [WAIT, STOP]:
        handle_wait_or_stop()
        continue

    if not safety_gate.will_execute_motion(action, state):
        log("would send", action)
        continue

    send_motion(action.command)
    reset_stability_filter()
    sleep(settle_time)
```

---

## 14. 不需要复刻的部分

如果目标只是复刻倒车算法，不需要复刻：

```text
HiSilicon MPP 初始化
OS08A20 驱动
OM 模型推理内部
UDP tee 的具体实现
VM monitor UI
Foxglove/ROS 可视化
```

这些可以替换为你自己的感知输入和底盘命令输出，只要满足：

```text
输入：稳定的停车位 polygon/状态
输出：短动作命令 ARC/MOVE/STOP
```

---

## 15. 移植到新小车前必须重新标定

不同小车必须重标：

```text
STE 中心值
STE 左右方向
D 正负方向
D 命令距离和实际距离比例
每个 STE 的实际曲率
相机到地面透视/坐标映射
slot_x_err 和真实横向误差的关系
```

不能直接假设：

```text
STE=120 一定是右弧
D=-6 一定是倒车 6cm
```

这些在当前车上成立，但移植车必须验证。

---

## 16. 给 AI 的最终指令建议

如果把本包喂给另一个 AI，可以这样要求：

```text
请阅读 PACKAGE_README.md、docs/ai_handoff_reverse_parking_logic_20260627.md、docs/current_reverse_parking_logic_20260627.md。
目标是复刻倒车泊车主逻辑，不需要复刻海思 SDK。
请保留 stepwise replanner、安全门、单步执行后重观测机制。
请重点改进低置信度 action_only_neighbor 情况下的动作降级策略：
- confidence < 0.30 禁止 6cm 大动作
- slot_completeness_can_refresh_geometry=false 时只允许 3/4cm 动作
- real_motion 下 action_only_neighbor 不允许直接执行 6cm
请输出修改方案和对应代码补丁。
```

---

## 17. 当前结论

这个包足够 AI 复刻当前倒车主逻辑，因为它包含：

```text
控制器源码
动作库
响应模型
成功/安全阈值
稳定过滤参数
底盘符号/曲率配置
当前验证日志
当前逻辑说明
```

它不包含完整板端 SDK，但复刻主算法不需要 SDK。移植时只需要把：

```text
检测输入适配
底盘命令输出适配
相机/坐标标定
```

替换成目标小车自己的实现即可。
