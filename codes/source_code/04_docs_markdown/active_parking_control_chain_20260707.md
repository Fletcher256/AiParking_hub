# 当前固定倒车控制链路（2026-07-08）

当前实车倒车默认链路固定为 **rollout_optimizer**。`line_follow` 保留为备用链路。

核心路线：

```text
YOLO / 车位相对姿态
  -> /opt/parking/autopark/board_parking_controller.py
  -> --strategy diy_first_frame_path_parking
  -> --diy-path-profile h1_structured_phase_parking
  -> --diy-path-structured-decision rollout_optimizer
  -> parking_rollout_optimizer_h1.json
  -> STM32 /dev/ttyUSB0
```

核心参数：

```text
--diy-path-structured-decision rollout_optimizer
--diy-path-rollout-optimizer-config-json /opt/parking/autopark/parking_rollout_optimizer_h1.json
--diy-path-effective-target-y-cm 1.5
--diy-path-success-lateral-tol-cm 2.0
--diy-path-success-heading-tol-deg 3.0
--diy-path-bottom-depth-success-y-cm 2.0
--diy-path-bottom-depth-success-heading-relax-cap-deg 3.0
```

## 新链路说明

`rollout_optimizer` 每步从当前姿态出发，枚举未来多步小车动作，用实测底盘模型预测终点，再只执行第一步。前中后期使用同一套束搜索，只是动作库和权重不同。

目标成功框：

```text
y_dist_cm <= 1.5
abs(lateral_cm) <= 2.0
abs(heading_deg) <= 3.0
```

后期 `y <= 15cm` 时禁止 `8cm` 大前进，只允许 `4cm` 前进，避免末端来回绕。

## 板端部署文件

```text
board_parking_controller.py
parking_controller_core.py
parking_rollout_optimizer.py
parking_line_follow_decision.py
parking_rollout_optimizer_h1.json
board_stm32_button_autopark.py
```

## 备用链路

如需回退，可把启动参数改回：

```text
--diy-path-structured-decision line_follow
```

`line_follow` 文档仍见：

```text
docs/parking_line_follow_decision_20260704.md
```

说明：parking_controller_core.py 是新增硬依赖，部署时不要只拷贝单个控制器文件。
