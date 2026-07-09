# 运动补偿线权重累积实现说明（2026-06-28）

## 目标

新增一条默认关闭的感知增强链路：把每帧 YOLO 车位框拆成四条车位边线，投影到地面 cm 坐标，再按当前泊车动作的本地 anchor 位姿累计到绝对局部坐标系。满足质量门时，再重建稳定车位框，供现有 `slot_relative_state -> action_replanner` 使用。

## 默认行为

- 默认关闭，不改变旧逻辑。
- 仅打开 `--slot-line-accum-enable`：只累计和打诊断日志，不替换规划输入。
- 同时打开 `--slot-line-accum-use-for-planning`：高权重 fused polygon 通过质量门后才替代原始 polygon 进入 `SlotStabilityFilter`。
- 打开 `--slot-line-accum-motion-capture`：真实 MOVE/ARC 期间后台消费 YOLO UDP 帧，并用 STM32 `TLM` 更新 pose；运动期间不做实时方向修正，只在动作结束后的新观测中影响规划。

## 关键文件

- `tools/parking_line_accumulator.py`
  - `MotionCompensatedSlotLineAccumulator`
  - `LineAccumulatorPoseTracker`
  - anchor/vehicle 坐标变换、线合并、衰减、fused polygon 重建。
- `tools/board_parking_controller.py`
  - 读取 `line_accumulator` 配置。
  - 新增 CLI 开关。
  - 正常检测后更新 accumulator。
  - 可选 fused slot_info 替换规划输入。
  - MOVE/ARC 发送路径支持 `TLM` observer callback。
- `configs/perception_filter.json`
  - 新增默认关闭的 `line_accumulator` 配置块。
- `tools/test_parking_line_accumulator.py`
  - 本地单元测试。

## 线合并门限

同类型边线才允许合并，并同时满足：

- 方向差 `<= merge_angle_deg`，默认 8°
- 垂距 `<= merge_distance_cm`，默认 5 cm
- 投影重叠 `>= merge_overlap_ratio`，默认 35%

单次权重：

```text
confidence * completeness_score * edge_length_score * moving_weight_scale
```

同时按 `decay_per_sec` 做时间衰减；动作后额外 `extra_scale=0.7` 衰减旧线，不清空 accumulator。

## 日志事件

新增事件均强制带：

```json
{"send_to_stm32": false, "motion_enabled": false, "actuator_control_allowed": false}
```

核心事件：

- `line_accumulator_update`
- `line_accumulator_motion_capture_start`
- `line_accumulator_motion_capture_stop`
- `line_accumulator_fused_candidate`
- `line_accumulator_fused_used`
- `line_accumulator_fused_rejected`

## 本地验证

已通过：

```powershell
.\.venv\Scripts\python.exe -m py_compile tools\parking_line_accumulator.py tools\test_parking_line_accumulator.py tools\board_parking_controller.py
.\.venv\Scripts\python.exe tools\test_parking_line_accumulator.py
.\.venv\Scripts\python.exe tools\test_perception_filter.py
```

合成 UDP no-motion 验证（调低测试配置的 `min_track_weight=1.0`）：

- `line_accumulator_fused_candidate > 0`
- `line_accumulator_fused_used > 0`
- `send_to_stm32 = 0`

产物：

- `artifacts/line_accum_synthetic_controller_min1.jsonl`
- `artifacts/line_accum_test_filter_min1.json`

## 板端验证建议

先只做 no-motion：

```text
action_replanner --replanner-dry-run --slot-line-accum-enable --slot-line-accum-use-for-planning
```

实车动作验证另行审批，第一轮限制 `max_steps=1`，仅验证动作后累积线是否改善重新稳定观测，不允许运动中实时修正方向。
