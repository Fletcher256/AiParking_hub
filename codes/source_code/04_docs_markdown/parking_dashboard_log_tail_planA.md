# 方案 A：泊车 JSONL 只读轨迹展示页

## 功能说明

`tools/parking_web_controller.py` 在原有本地 Web 控制台基础上新增了一个只读 viewer：

- 页面：`/viewer`
- 只读状态 API：`/api/parking-log/state`
- 只读事件 API：`/api/parking-log/events`

该功能只读取本机指定的泊车 JSONL 日志，实时解析泊车状态、当前位姿、候选动作、候选轨迹、动作评分和 STM32 摘要，并在网页中绘制俯视轨迹图。

## 指定日志路径

两种方式任选其一：

```powershell
.\.venv\Scripts\python.exe tools\parking_web_controller.py `
  --host 127.0.0.1 `
  --port 8765 `
  --parking-log-jsonl D:\parking_board_agent\artifacts\dashboard_demo\demo_parking_candidates.jsonl
```

或使用环境变量：

```powershell
$env:PARKING_DASHBOARD_LOG_JSONL="D:\parking_board_agent\artifacts\dashboard_demo\demo_parking_candidates.jsonl"
.\.venv\Scripts\python.exe tools\parking_web_controller.py --host 127.0.0.1 --port 8765
```

如果日志不存在或尚未写入，API 会返回 `WAITING`，页面显示 `Waiting for log` 类状态，不会崩溃。

## 打开只读页面

本机访问：

```text
http://127.0.0.1:8765/viewer
```

原控制台 `/` 保持原有行为，只额外增加了一个 `Read-only Log Viewer` 跳转按钮。

## 给评委扫码访问

当前 Web 控制台默认拒绝 `0.0.0.0`，因此默认只适合本机访问。若需要给评委扫码，建议在 Windows 侧使用已有局域网转发/反向代理方案，把本机 `127.0.0.1:8765/viewer` 映射成只读外部 URL；不要暴露原 operator/control 页面。

## 数据字段说明

`/api/parking-log/state` 输出：

- `status`：`WAITING / PLANNING / EXECUTING / STOPPED / SUCCESS / VISION_LOST / ERROR`
- `current_pose`：`y_dist_cm / lateral_cm / heading_deg`
- `locked_initial_pose`
- `visual_pose`
- `confidence`
- `min_margin_px`
- `line_risk / effective_line_risk`
- `chosen_action`
- `step_index`
- `total_reverse_cm`
- `total_forward_shuffle_cm`
- `stm32`：`ack / done / stat_summary / odom_progress_cm / yaw_delta_deg / imu / drop`
- `stop_reason / success_reason`
- `candidates[]`：标准化后的候选动作、分数、阻断原因、预测位姿和轨迹点

## 安全边界

本新增方案只做日志读取和网页展示：

- 只读读取 JSONL 文件；
- 不发送 STM32 控制命令；
- 不创建 arm file；
- 不启动真实泊车；
- 新增 API 全部为 GET；
- `/viewer` 页面没有控制按钮；
- 未修改 `board_parking_controller.py` 泊车决策逻辑。

原 `/` operator/control 页面仍保留既有行为，本方案不改变它。

## Demo 日志测试

已提供示例日志：

```text
D:\parking_board_agent\artifacts\dashboard_demo\demo_parking_candidates.jsonl
```

启动后访问：

```text
http://127.0.0.1:8765/viewer
http://127.0.0.1:8765/api/parking-log/state
```

页面应显示：

- 当前状态卡片；
- 车位框、当前位姿、初始位姿；
- 多条候选轨迹；
- selected 轨迹绿色高亮；
- blocked/rejected 轨迹红色；
- 候选动作评分表；
- 安全/传感摘要。

## 后续可扩展项

- 雷达安全状态接入；
- 实时视频 overlay；
- 多次泊车成功率统计；
- 离线回放时间轴；
- 将板端 JSONL 自动同步到本机展示目录。
