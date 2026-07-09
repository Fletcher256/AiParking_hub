# P0 稳定基线收口（2026-07-07）

## 目标

把当前已经形成的实车倒车成果先冻结成一个可复现、可验证、可继续迭代的 P0 稳定基线。P0 只做收口，不扩展算法能力，不改板端运行状态。

## P0 基线结论

当前默认实车链路固定为：

```text
OS08A20 / YOLO
  -> UDP 127.0.0.1:24580
  -> /opt/parking/autopark/board_parking_controller.py
  -> --strategy diy_first_frame_path_parking
  -> --diy-path-profile h1_structured_phase_parking
  -> --diy-path-structured-decision line_follow
  -> STM32 /dev/ttyUSB0
```

机器可读基线清单：

```text
configs/p0_stable_baseline_manifest.json
configs/active_parking_control_chain.json
```

## 不再作为默认启动链路

以下链路只保留为历史对照/手动实验，不能作为默认启动：

```text
h1_lattice_mpc
path_template_planner
```

## 一键本地基线验证

新增本地离线验证脚本：

```text
tools/p0_baseline_validate.py
```

运行：

```powershell
.\.venv\Scripts\python.exe tools\p0_baseline_validate.py
```

验证内容：

```text
1. 必要文件存在
2. active control chain 固定为 line_follow
3. 默认 argv 不包含 h1_lattice_mpc / path_template_planner
4. 部署文档包含 parking_controller_core.py 新依赖
5. 关键 Python 文件可 py_compile
6. 离线单元/集成测试通过
```

验证报告写入：

```text
artifacts/p0_baseline/p0_baseline_validation_<timestamp>.json
artifacts/p0_baseline/latest_p0_baseline_validation.json
```

## 离线回归测试集合

```text
tools.test_parking_controller_core
tools.test_parking_line_follow_decision
tools.test_h1_line_follow_integration
tools.test_perception_filter
tools.test_parking_line_accumulator
```

## P0 验收标准

P0 视为通过时必须满足：

```text
active_chain_id == line_follow
--diy-path-structured-decision line_follow
YOLO UDP == 127.0.0.1:24580
STM32 trigger == CTR_PK
本地 py_compile 全部通过
本地 unittest 全部通过
```

## 本轮验证结果

2026-07-07 已运行：

```powershell
.\.venv\Scripts\python.exe tools\p0_baseline_validate.py
```

结果：

```text
checks_total: 50
checks_passed: 50
checks_failed: 0
active_chain_id: line_follow
tests_skipped: false
```

报告：

```text
artifacts/p0_baseline/p0_baseline_validation_20260707_173033.json
artifacts/p0_baseline/latest_p0_baseline_validation.json
```

## 清理策略

当前工作区存在大量历史调试脚本、临时文档和演示产物。P0 阶段不直接删除，避免误删可复现实验材料。

建议下一步单独执行“归档清理”：

```text
1. 只保留 P0 manifest 声明的运行/验证必需文件在主路径
2. 历史脚本移动到 archive/ 或 docs/history/
3. tmp_*.docx/pdf/txt、rendered_*、scratch_* 统一归档到 artifacts/reports/
4. 归档前先生成文件清单，不做直接删除
```

## 后续迭代入口

P0 通过后再进入：

```text
P1: 实车 L0 稳定泊车闭环
P2: L1 初始位姿泛化
P3: 动作模板 MPC
P4: dToF 空间安全融合
```
