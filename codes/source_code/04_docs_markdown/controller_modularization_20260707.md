# 控制器模块化记录（2026-07-07）

## 已完成：第一刀低风险抽离

从 `tools/board_parking_controller.py` 抽出纯标准库、无串口/无板端副作用的配置与判据核心：

```text
tools/parking_controller_core.py
```

当前该模块包含：

```text
DEFAULT_SUCCESS_CRITERIA
DEFAULT_PERCEPTION_FILTER
load_success_criteria()
load_perception_filter()
slot_x_divergence_defer_review()
min_margin_defer_review()
unreliable_geometry_planning_review()
evaluate_parking_criteria()
```

控制器仍保留原默认链路和 CLI 行为，只改为从 `parking_controller_core.py` 导入上述逻辑。

## 本轮验证

```powershell
.\.venv\Scripts\python.exe -m py_compile tools\parking_controller_core.py tools\board_parking_controller.py
.\.venv\Scripts\python.exe -m unittest tools.test_parking_controller_core tools.test_parking_line_follow_decision tools.test_h1_line_follow_integration tools.test_perception_filter tools.test_parking_line_accumulator
```

结果：

```text
Ran 32 tests
OK
```

## 下一步拆分顺序

1. `parking_slot_geometry.py`：抽 YOLO mask/polygon -> quad/edges/corridor 的纯几何逻辑。
2. `parking_state_adapter.py`：抽 slot_relative_state flatten、planner state 字段转换、JSONL schema。
3. `parking_safety_gate.py`：抽 arm/no-motion/vision-lost/line-risk/total-distance 等运行时安全门。
4. `parking_stm32_executor.py`：抽 STM32 串口发送、STAT 解析、运动执行与结果日志。
5. `parking_controller_main.py`：最终把 `board_parking_controller.py` 降成 CLI glue + 主循环编排。

## 部署注意

板端 `/opt/parking/autopark/` 后续不能只同步单个控制器文件。当前建议完整同步：

```text
board_parking_controller.py
parking_controller_core.py
parking_line_follow_decision.py
parking_fusion.py
parking_line_accumulator.py
parking_kinematic_lattice.py
```

其中 `parking_controller_core.py` 是新增硬依赖；`parking_fusion.py`、`parking_line_accumulator.py`、`parking_kinematic_lattice.py` 仍按当前控制器的可选/现有链路导入策略保留。
