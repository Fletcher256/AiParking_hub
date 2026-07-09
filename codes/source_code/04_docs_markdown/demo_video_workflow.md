# 比赛演示视频素材工具链

## 目标

为三种初始位姿下的小车自动泊车过程生成“旁路观测 + 离线回放 + 视频叠加素材”。工具链只读取已有 controller JSONL、YOLO/实车图像目录并生成 PNG/MP4 素材，不参与泊车闭环。

展示重点：

1. 小车摄像头视角的 YOLO 分割 / polygon；
2. homography 坐标转换后的车位相对关系；
3. 候选路径 / 候选动作规划；
4. 每一步选择动作的判断依据；
5. STM32 执行反馈；
6. 最终泊车结果。

## 三个姿态设计

- `pose_A`：横向偏差明显的起步，用于展示 lateral 收敛。
- `pose_B`：航向角偏差明显的起步，用于展示 heading debt 支付。
- `pose_C`：接近终端 / terminal shuffle 微调场景，用于展示最后姿态修正。

## 输出目录结构

标准输出目录：

```text
artifacts/demo_video_package/<stamp>/
  pose_A/
    raw/
    frames/
    overlays/
    topdown/
    decision/
    composite/
    steps.json
    candidates.json
    summary.json
    decisions.md
  pose_B/
  pose_C/
  demo_logs/
  final_assets/
  run_config.json
  README.md
```

每个 `pose_*` 目录对应一次泊车演示。

## 新增脚本

- `tools/demo_video_log_extract.py`
  - 读取 controller JSONL，输出 `steps.json / candidates.json / summary.json / decisions.md`。
- `tools/demo_video_render_topdown.py`
  - 根据 `steps.json` 生成 homography / topdown 风格俯视图。
- `tools/demo_video_render_decision_cards.py`
  - 每步生成一张“判断依据 / candidates”说明卡。
- `tools/demo_video_render_composite.py`
  - 合成四宫格 1920x1080 PNG。
- `tools/demo_video_make_clip.py`
  - 如果系统有 ffmpeg，则从 composite PNG 生成 mp4；否则保留图片序列。
- `tools/demo_video_package.py`
  - 一键离线打包三组日志。
- `tools/demo_video_utils.py`
  - 只读解析和绘图公共函数。

## 使用 demo 数据测试

无需真实泊车日志时，直接生成 demo：

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_package.py `
  --demo `
  --stamp demo_test `
  --fps 2 `
  --hold-sec 0.2
```

输出：

```text
D:\parking_board_agent\artifacts\demo_video_package\demo_test\
```

至少应生成：

- `pose_A/steps.json`
- `pose_A/summary.json`
- `pose_A/topdown/frame_0001.png`
- `pose_A/decision/frame_0001.png`
- `pose_A/composite/frame_0001.png`
- `README.md`

如果本机未安装 `ffmpeg`，`final_assets/*.mp4` 会跳过，图片序列仍可用于剪辑软件。

## 使用三次真实泊车日志生成素材

将三次真实 controller JSONL 分别传入：

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_package.py `
  --pose-a-log D:\path\to\pose_A.jsonl `
  --pose-b-log D:\path\to\pose_B.jsonl `
  --pose-c-log D:\path\to\pose_C.jsonl `
  --stamp real_three_pose_demo `
  --fps 2 `
  --hold-sec 0.8
```

## 传入 YOLO 图像目录

如果已有每步或近似对齐的 YOLO overlay / mask 图像目录：

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_package.py `
  --pose-a-log D:\path\to\pose_A.jsonl `
  --pose-b-log D:\path\to\pose_B.jsonl `
  --pose-c-log D:\path\to\pose_C.jsonl `
  --pose-a-yolo-dir D:\path\to\pose_A_yolo_frames `
  --pose-b-yolo-dir D:\path\to\pose_B_yolo_frames `
  --pose-c-yolo-dir D:\path\to\pose_C_yolo_frames `
  --real-video-dir D:\path\to\external_camera_frames `
  --stamp real_with_yolo
```

对齐策略：当前 MVP 按文件名排序后以 step index 取最近帧。如果没有图像，则自动生成占位图，不报错。

## 真实拍摄推荐采集内容

建议每次演示同时保存：

1. 固定机位实车视频或抽帧目录；
2. controller JSONL；
3. YOLO image / overlay；
4. STM32 执行日志字段已经包含在 controller JSONL 的 `stm32_result / odom_delta` 中。

如果要录制 YOLO 画面，保持它为旁路观察：只监听 UDP 或读取保存帧，不向控制器发送动作命令。

## 安全边界

本工具链保证：

- 不修改泊车主控制逻辑；
- 不修改 `board_parking_controller.py` 决策逻辑；
- 不启动真实泊车；
- 不创建 `/tmp/parking_armed`；
- 不发送 STM32 / MOVE / ARC / SERVO / STOP 命令；
- 不让可视化、录制、网页或渲染参与控制闭环；
- 所有新增脚本只读日志、只读图像、生成图片/视频素材。

## 视频剪辑建议

推荐成片结构：

1. 开场直接展示三次成功泊车结果；
2. 感知：YOLO mask/polygon；
3. 坐标转换：topdown 车位和小车相对位姿；
4. 候选规划：多条候选轨迹和 selected 轨迹；
5. 实车闭环：每步 STOP/observe/replan；
6. 安全机制：line risk / IMU / ACK/DONE / no-progress；
7. 指标总结：步数、最终 y/lateral/heading、成功率。

## 后续可扩展

- 用真实时间戳对齐 YOLO 帧和 controller step；
- 接入外部固定机位视频自动抽帧；
- 生成带时间轴的完整回放 HTML；
- 统计多次泊车成功率和最终误差分布；
- 接入雷达/ToF 安全状态展示。

## Camera + YOLO 离线叠加

新增 `tools/demo_video_render_yolo_overlay.py`：

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_render_yolo_overlay.py `
  --steps-json D:\parking_board_agent\artifacts\demo_video_package\real_demo\pose_A\steps.json `
  --frame-dir D:\path\to\camera_or_yolo_raw_frames `
  --out-dir D:\parking_board_agent\artifacts\demo_video_package\real_demo\pose_A\overlays
```

工作方式：

- 从 `steps.json` 读取每步的 `mask_polygon / slot_polygon_px / slot_edges_px`；
- 从 `--frame-dir` 读取本机保存的摄像头帧；
- 将 polygon、拟合四边形和 entry/back/left/right edge 叠加到图像上；
- 如果没有摄像头帧，自动生成占位图，但仍然画日志里的 polygon；
- 输出 `overlays/frame_0001.png ...`。

因此真实演示时可以只保存 controller JSONL 和相机帧，后期在本机离线叠加 YOLO/polygon，不让叠加逻辑进入控制闭环。

## Homography/topdown 运动动画

新增 `tools/demo_video_render_topdown_animation.py`：

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_render_topdown_animation.py `
  --steps-json D:\parking_board_agent\artifacts\demo_video_package\real_demo\pose_A\steps.json `
  --out-dir D:\parking_board_agent\artifacts\demo_video_package\real_demo\pose_A\topdown_animation `
  --frames-per-step 10
```

每个倒车 step 会展开成多帧动画，包含：

- homography/topdown 坐标系；
- 车位框；
- 当前小车从 before pose 到 after pose 的运动插值；
- 该步实时规划出的 candidate trajectories；
- selected path 绿色；
- blocked/rejected 红色；
- 普通候选蓝色；
- target pose；
- 每步选择动作；
- score / predicted pose；
- 判断依据；
- STM32 ACK/DONE/progress/yaw/IMU/DROP 反馈。

如果安装了 ffmpeg，一键 package 会额外尝试生成：

```text
final_assets/pose_A_topdown_animation.mp4
final_assets/pose_B_topdown_animation.mp4
final_assets/pose_C_topdown_animation.mp4
```

未安装 ffmpeg 时保留 PNG 序列，可直接导入剪辑软件。

## 一键打包时的新增参数

```powershell
.\.venv\Scripts\python.exe D:\parking_board_agent\tools\demo_video_package.py `
  --pose-a-log D:\logs\pose_A.jsonl `
  --pose-b-log D:\logs\pose_B.jsonl `
  --pose-c-log D:\logs\pose_C.jsonl `
  --pose-a-yolo-dir D:\frames\pose_A_camera `
  --pose-b-yolo-dir D:\frames\pose_B_camera `
  --pose-c-yolo-dir D:\frames\pose_C_camera `
  --animation-frames-per-step 10 `
  --stamp real_demo_with_overlay_animation
```

`--pose-*-yolo-dir` 可以是原始摄像头帧，也可以是已保存的 YOLO raw/overlay 帧。脚本会在其上继续叠加日志里的 polygon 和边信息。
