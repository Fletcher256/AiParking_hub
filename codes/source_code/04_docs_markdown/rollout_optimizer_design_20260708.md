# 全程滚动优化泊车设计

## 目标

新建一条独立主线：`rollout_optimizer`。

它不再按“前期倒入、中期修正、后期补救”分三套逻辑，而是全程使用同一个滚动优化框架：

```text
当前姿态 -> 枚举未来动作序列 -> 用实测模型预测 -> 打分 -> 执行第一步 -> 停车重观测 -> 重算
```

目标成功条件先设为：

```text
y_dist_cm <= 1.5
abs(lateral_cm) <= 2.0
abs(heading_deg) <= 3.0
```

后续视觉稳定后再考虑收紧到：

```text
abs(lateral_cm) <= 1.5
abs(heading_deg) <= 2.0
```

## 为什么要换主线

现有 `line_follow` 能把车倒进去，但它的问题是：

```text
1. 一次泊入只追局部线跟随，不直接优化最终姿态。
2. 到末端才发现角度还差几度。
3. 末端微调动作偏粗，容易出现前进/倒车来回绕。
4. 前期动作可能把车带入后期难修的姿态。
```

新主线从第一步开始就预测最终姿态，避免“先进去再补救”。

## 总体结构

```text
YOLO车位多边形
  -> 当前相对车位姿态 y/lateral/heading
  -> rollout_optimizer
  -> 动作序列搜索
  -> 实测运动模型预测
  -> 最优第一步动作
  -> STM32执行
  -> 停车观测
  -> 下一轮规划
```

新增文件建议：

```text
tools/parking_rollout_optimizer.py
configs/parking_rollout_optimizer_h1.json
tools/test_parking_rollout_optimizer.py
```

控制器新增入口：

```text
--diy-path-structured-decision rollout_optimizer
```

保留旧链路：

```text
--diy-path-structured-decision line_follow
```

## 输入

每次规划输入：

```text
y_dist_cm
lateral_cm
heading_deg
near_side
last_actions
vision_quality
step_count
total_reverse_cm
total_forward_cm
```

其中核心必需项：

```text
y_dist_cm
lateral_cm
heading_deg
```

## 动作库

动作库按阶段变化，但算法不变。

### 前期

适用：

```text
y_dist_cm > 35
```

动作：

```text
方向：倒车为主，必要时前进
距离：7cm / 9cm
前进距离：6cm / 8cm
舵角：60 / 75 / 85 / 100 / 115 / 130 / 140
预测深度：6~7步
保留候选：32条
```

目标：

```text
不要只求快，要提前形成后期容易摆正的姿态。
```

### 中期

适用：

```text
15 < y_dist_cm <= 35
```

动作：

```text
倒车距离：5cm / 7cm
前进距离：4cm / 6cm
舵角：60 / 70 / 80 / 90 / 100 / 110 / 120 / 130 / 140
预测深度：5~6步
保留候选：32条
```

目标：

```text
横向和角度同步收敛，避免末端大补救。
```

### 后期

适用：

```text
y_dist_cm <= 15
```

动作：

```text
倒车距离：4cm / 5cm
前进距离：4cm
舵角：60 / 70 / 80 / 90 / 100 / 110 / 120 / 130 / 140
预测深度：4~5步
保留候选：64条
```

目标：

```text
角度优先压到3度内，横向压到2cm内，深度到1.5cm以内。
```

注意：暂时不用2cm、3cm命令作为主动作，因为当前车有死区，太小可能动作不稳定。后面如果实测支持，再加更小动作。

## 运动模型

不用纯理论模型，优先使用实测模型：

```text
configs/chassis_kinematics.json
/opt/parking/autopark/chassis_kinematics.json
/opt/parking/autopark/terminal_shuffle_forward_kinematics.json
```

预测逻辑：

```text
command_cm -> expected_progress_cm
ste -> deg_per_cm
方向 -> yaw符号
progress + yaw -> 新姿态
```

后续加入在线修正：

```text
同一个方向和舵角，如果实际 yaw_delta 长期偏大或偏小，更新 runtime_deg_per_cm。
```

## 打分函数

每条未来动作序列的分数越低越好。

基础项：

```text
heading_score = heading_weight * abs(final_heading_deg)
lateral_score = lateral_weight * abs(final_lateral_cm)
y_score = y_weight * depth_error
forward_penalty = forward_weight * forward_cm
switch_penalty = switch_weight * direction_switch_count
step_penalty = step_weight * action_count
clearance_penalty = side_clearance_risk
oscillation_penalty = repeat_area_or_reverse_pattern
```

终点硬惩罚：

```text
if abs(final_heading_deg) > 3.0: big penalty
if abs(final_lateral_cm) > 2.0: big penalty
if final_y_dist_cm > 1.5: big penalty
```

阶段权重建议：

```text
前期：可达性、贴边风险、最终趋势更重要
中期：横向和角度同步收敛
后期：角度最高，横向第二，深度第三
```

后期建议权重：

```text
heading_weight = 30
lateral_weight = 12
y_weight = 8
forward_weight = 2
switch_weight = 8
step_weight = 1
```

## 搜索方法

使用束搜索。

伪代码：

```text
beam = [当前状态]
for depth in 1..horizon:
    next = []
    for node in beam:
        for action in action_library(stage):
            predicted = simulate(node.pose, action)
            if violates_hard_safety(predicted): continue
            score = score_sequence(predicted, node.history + action)
            next.append(predicted_node)
    beam = best N nodes from next

best = lowest final score in beam
return best.first_action
```

## 防振荡规则

必须防止来回折腾：

```text
1. 同一位置附近重复前进/倒车，惩罚加大。
2. 连续前进次数限制。
3. 前进总距离限制。
4. 如果预测分数改善小于阈值，不执行换向动作。
5. 连续3次实际没有改善，停止并报 no_converge。
```

建议阈值：

```text
min_score_improve_for_switch = 5.0
max_forward_total_cm = 16.0
max_direction_switch_count = 6
no_improve_stop_count = 3
```

## 停止条件

成功：

```text
y_dist_cm <= 1.5
abs(lateral_cm) <= 2.0
abs(heading_deg) <= 3.0
```

失败或停止：

```text
超过最大步数
超过最大总里程
连续多次没有改善
没有安全候选动作
视觉/里程状态异常
```

## 离线验证计划

第一阶段只离线，不上板、不动车。

输入：最近实车日志：

```text
/tmp/parking_manual_line_follow_20260708_heading3_depth1.jsonl
```

验证内容：

```text
1. 读取每一步的姿态。
2. 用新算法重新规划下一步。
3. 对比旧算法当时的动作。
4. 重点看末端 y=0.428, lateral=-0.908, heading=4.088。
5. 检查新算法是否避免 8cm 大前进循环。
```

本地输出建议：

```text
artifacts/rollout_optimizer/replay_compare_*.json
artifacts/rollout_optimizer/replay_compare_*.md
```

## 第一版边界

第一版只做：

```text
1. 离线动作搜索。
2. 离线预测。
3. 离线回放对比。
```

不做：

```text
1. 不接 STM32。
2. 不替换当前 line_follow。
3. 不上板。
4. 不动车。
```

## 接入实车前必须满足

离线必须先通过：

```text
1. 末端不会反复大前进。
2. 从最近日志末端姿态能给出合理动作或明确不可改善。
3. 前中期动作不会明显比旧算法更激进。
4. 所有预测和打分可解释。
5. 单测覆盖动作积分、打分、束搜索、停止条件。
```

通过后再考虑加控制器入口：

```text
--diy-path-structured-decision rollout_optimizer
```
