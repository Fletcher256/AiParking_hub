# Claude Prompt: 任意位置自动泊车完整计划

请你作为自动驾驶/机器人控制/嵌入式系统方向的高级工程师，基于下面的项目背景，为我制定一份完整、详细、可执行的“任意位置自动泊车”实现计划。

## 总目标

我要实现小车可以在尽可能宽的初始位置范围内自动泊车。

长期目标可以描述为：

```text
实现任意位置自动泊车
```

但请你不要简单假设“任意位置”可以一步到位。请你先定义能力边界和阶段目标，例如：

- 固定起点附近泊车
- 车位可见范围内泊车
- 左右偏移一定范围内泊车
- 角度偏差一定范围内泊车
- 需要前进调整后再倒车入库
- 车位局部可见时泊车
- 更接近真正任意位置的自动泊车

请把“任意位置自动泊车”拆成从低到高的能力等级，并给出每个等级需要实现的感知、规划、控制和验证内容。

## 硬件与运行环境

当前系统由以下部分组成：

```text
OS08A20 摄像头
  -> SS928 / Euler Pi 板端 YOLO 车位识别
  -> UDP 127.0.0.1:24580
  -> 板端 Python 控制器
  -> STM32
  -> 电机和舵机
```

最终运行目标：

```text
不依赖电脑 / VM / ROS
靠板端摄像头 + YOLO + STM32 控制链闭环完成泊车
```

电脑和 VM 可以用于开发、训练、日志分析、模型升级和离线回归，但最终泊车过程不应该依赖电脑。

## 当前工作区与目标设备

项目目录：

```text
D:\parking_board_agent
```

板端：

```text
SS928 / Euler Pi / openEuler Embedded
SSH: root@192.168.137.2
串口 STM32: /dev/ttyUSB0
```

VM：

```text
Ubuntu VM
SSH: ebaina@192.168.137.100
```

板端主要路径：

```text
/opt/parking/autopark/
/opt/sample/parking_yolo_seg_safe/
```

## 重要安全约束

请在计划中保留这些安全门：

```text
没有 --arm 不允许运动
没有 /tmp/parking_armed 不允许运动
dry-run 永远不发送运动命令
YOLO 丢失超过 0.5 秒 STOP
线框余量过小 STOP
状态发散 STOP
STM32 状态异常 STOP
总运动距离上限 STOP
异常退出路径尝试 STOP
实车测试必须从单步动作开始
```

不要把未验证的规划器直接接入实车连续运动。

## 当前已经完成的工作

### 1. 感知链路

板端 YOLO 可以运行，并把车位检测 JSON 发到：

```text
127.0.0.1:24580
```

控制器可以接收 YOLO polygon，并提取：

- 车位 polygon
- 入口边
- 左右边线
- 中心线
- 车位朝向
- corridor 指标

### 2. STM32 链路

已验证 STM32 命令链路：

```text
SERVO
PWM_STAT
ARC
MOVE
STAT
STOP
```

舵机 PWM 已验证，例如：

```text
STE=60 -> ANG=60.0, PULSE=1333
STE=90 -> ANG=90.0, PULSE=1500
```

### 3. 失败经验

曾尝试固定走廊控制 / 像素闭环 / 分段倒车，但小车会压线或停不进去。

关键结论：

```text
问题主要不是舵机没有发，而是路径规划和动作响应模型不正确。
```

实测动作：

```text
ARC D=-6.0 STE=60 V=1
```

结果：

```text
lon_cm: 34.11 -> 31.70
lat_cm: -0.01 -> -1.68
corridor_x_err_px: 18.0 -> 46.0
corridor_min_margin_px: 186.0 -> 162.0
```

判定：

```text
STE=60 变差，不适合作为该姿态下的入口弧线。
```

### 4. 长期架构决策

项目已经决定不再以“固定倒车流程”为主路线。

新的主路线是：

```text
YOLO 车位 polygon
  -> 车位相对位姿 slot_relative_state
  -> 动作模板库 action library
  -> 候选动作评分
  -> 执行一个短动作
  -> 停车重新观察
  -> 每步重规划
```

也就是：

```text
relative-pose + action-template replanning
```

固定分段倒车只作为狭窄初始姿态下的 fallback。

## 已完成的软件阶段

### 阶段 1：观测状态

已实现：

```text
slot_relative_state
```

主要字段：

- `slot_x_err_px`
- `slot_entry_x_err_px`
- `slot_heading_err_deg`
- `left_margin_px`
- `right_margin_px`
- `min_margin_px`
- `line_risk`
- `slot_y_dist_cm`
- `slot_lateral_cm`
- `pose_quality`
- `phase_hint`

当前 dry-run 稳定性：

```text
slot_x_err_px stdev ~= 0.542 px
slot_heading_err_deg stdev ~= 0.177 deg
min_margin_px stdev ~= 0.576 px
slot_lateral_cm stdev ~= 0.052 cm
pose_quality mean ~= 0.938
```

### 阶段 2：动作模板库与离线评分器

已实现：

```text
configs/parking_action_library.json
configs/parking_action_response_model.json
tools/parking_action_scorer.py
```

当前动作库：

```text
MOVE D=-6.0 V=1
ARC D=-6.0 STE=60 V=1
ARC D=-6.0 STE=75 V=1
ARC D=-6.0 STE=105 V=1
ARC D=-6.0 STE=120 V=1
```

当前评分器基于阶段 1 的状态日志，推荐下一步最值得标定：

```text
ARC D=-6.0 STE=120 V=1
origin = prior
confidence = 0.25
```

注意：这只是下一步标定建议，不是已验证的自动执行动作。

## 当前项目文档

请参考这些文档的含义，并在计划中延续它们的架构：

```text
docs/autopark_long_term_memory.md
docs/autopark_stage1_observation_20260612.md
docs/autopark_stage2_action_library_20260612.md
docs/autopark_status_report_20260612.md
docs/autopark_multistage_plan_20260612.md
```

## 我希望你输出的内容

请输出一份完整详细计划，至少包含以下部分。

### A. 目标重定义

请重新定义“任意位置自动泊车”的合理工程含义：

- 最终愿景
- 短期可实现目标
- 中期目标
- 长期目标
- 不应承诺的能力边界

请明确哪些情况在当前硬件上暂时不支持。

### B. 系统架构

请画出或描述完整架构：

```text
感知层
状态估计层
动作响应模型层
路径/动作规划层
控制执行层
安全监督层
日志与回归层
```

请说明每层输入、输出、关键算法和风险。

### C. 算法路线

请比较并选择适合当前小车的路线：

- 固定分段倒车
- 纯像素闭环
- 车位坐标系闭环
- 动作模板库 + 每步重规划
- Reeds-Shepp 简化版
- Hybrid A*
- 强化学习 / 正负反馈学习

请说明为什么当前最适合先做：

```text
动作模板库 + 每步重规划
```

并说明什么时候再升级到 Reeds-Shepp / Hybrid A*。

### D. 状态定义

请基于 `slot_relative_state` 设计完整状态向量：

- 必要字段
- 可选字段
- 置信度与稳定性
- 压线风险
- 车位可见性
- 视觉丢失处理
- 状态是否适合规划

请指出当前字段还缺什么。

### E. 动作模板库

请设计动作库：

- 倒车直行
- 小左弧
- 大左弧
- 小右弧
- 大右弧
- 反打摆正
- 必要时前进修正
- STOP / WAIT

每个动作要有：

- command
- 适用 phase
- 距离上限
- 舵角
- 风险
- 预期状态变化
- 需要如何实测标定

### F. 动作响应标定方案

请制定实车标定方案：

- 如何保证同一初始位姿
- 每次只执行一个动作
- 执行动作前记录什么
- 执行动作后记录什么
- 如何判定动作变好/变差
- 如何更新 response model
- 每个动作至少需要多少样本
- 如何处理噪声和偶然误检

请特别说明下一步是否应该测：

```text
ARC D=-6.0 STE=120 V=1
```

以及测完如何判断是否推广到 12cm / 20cm。

### G. 一步重规划器

请设计一步重规划器：

```text
当前状态 -> 枚举动作 -> 预测下一状态 -> 打分 -> 选最优动作
```

请给出：

- cost function
- 权重设计
- 硬约束
- 软约束
- 如何避免动作抖动
- 如何避免一直选同一个错误动作
- 如何处理未标定动作

### H. 多步 lookahead

请说明什么时候从一步规划升级到 2-3 步 lookahead。

要求：

```text
可以模拟多步
但每次实车只执行第一步
执行后重新观察和重规划
```

### I. 实车测试流程

请给出严格的实车测试阶段：

1. dry-run
2. 单步标定
3. 单步推荐但人工批准执行
4. 最多两步连续
5. 多步自动但有总距离上限
6. 接近完整泊车
7. 更大初始位置范围

每个阶段给出通过标准和停止条件。

### J. 日志、回放、回归

请设计日志格式和回归流程：

- 每次动作前状态
- 动作命令
- STM32 ACK/DONE
- PWM/STAT
- 动作后状态
- delta
- verdict
- 评分器输出
- 模型升级前后对比

请说明如何用历史日志回放验证算法。

### K. YOLO 模型升级影响

我计划后续升级 YOLO 模型。升级前后模型格式一样，只是训练量不同。

请说明：

- 模型升级前需要保存哪些基准集
- 升级后如何比较
- 哪些指标变化会影响控制器
- 如何避免模型升级导致动作方向反了或状态跳变

### L. 软件实施计划

请把下一步开发拆成具体任务：

- 文件/模块设计
- 数据结构
- CLI 命令
- dry-run 验证
- 板端部署
- 实车标定
- 文档更新

请按优先级排序。

### M. 风险清单

请列出主要风险：

- YOLO polygon 不稳定
- homography 不准
- 舵机死区/响应慢
- 命令距离与实际距离不一致
- 车位丢失
- 压线
- 初始位置超出能力范围
- 模型升级导致状态变化
- 板端性能不足

每个风险给出缓解方案。

### N. 最终交付路线图

请给出一个从当前状态到“尽可能任意位置自动泊车”的路线图：

- 1 天内能做什么
- 2-3 天能做什么
- 1 周能做什么
- 后续扩展怎么做

## 当前我最关心的问题

请重点回答：

1. 当前“动作模板库 + 每步重规划”路线是否正确？
2. 如何从当前阶段 2 继续推进到能实车泊车？
3. 是否应该继续先测 `STE=120`？
4. 如何设计一个真正能扩展到较宽初始位置范围的规划器？
5. 要做到接近“任意位置”，还缺哪些核心能力？

请输出具体、工程化、可执行的计划，不要只给泛泛的自动驾驶概念。
