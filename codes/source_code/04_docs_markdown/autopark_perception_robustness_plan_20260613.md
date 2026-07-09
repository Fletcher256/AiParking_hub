# 感知噪声滤除计划：抗跳变 + 抗丢失（Codex 执行版）- 2026-06-13

> 目标：让 YOLO 车框的偶发跳变、偶发单帧消失**不再触发停车或破坏稳定状态**，同时**不削弱对真实危险（压线）的响应**。
> 改动集中在 `board_parking_controller.py` 的 `SlotStabilityFilter` 与 vision-lost 主循环段，纯标准库。
> 安全总原则不变：滤波只影响"用哪个状态去规划/判定"，绝不影响"运动需要 --arm + arm file"，绝不允许用 coast 状态发起**新**运动。

---

## 0. 三类视觉问题，三种处理（先分清，别混为一谈）

| 问题 | 现象 | 物理判据 | 正确处理 | 现状 |
|---|---|---|---|---|
| 抖动 jitter | 值在小范围噪声波动（±0.5px 级） | 正常 | 时间平滑 | ✅ 有（但用均值） |
| 跳变 outlier | 单帧框突然跳到很远 | 静止观察期车没动→框不可能真跳→必是噪声 | **拒绝该帧、保留窗口** | ❌ 反了：清窗信新帧 |
| 消失 dropout | 几帧没有检测 | 静止期世界没变→旧状态仍有效 | **hold 上一稳定态 + 宽限期** | ❌ 瞬时奔 STOP |

**本项目的有利先验**：架构是"停—看—走"，**观察期车是静止的**。车不动 → 车位真实位姿不可能变 → 观察期内任何大的帧间变化在物理上都不可能是真的，必然是噪声。这给了一个极强、几乎零误判的离群判据：**静止观察期，大跳变一律拒绝，丢失一律 hold。** 运动刚结束后车已停稳，同样适用。

---

## A. 平滑层：均值 → 中值（半天，板端）

`SlotStabilityFilter.fused()` 把所有 `mean(...)` 改为 `median(...)`。中值对单个离群点完全免疫（均值不免疫）。

纯标准库 median（无 numpy）：

```python
def median(values):
    s = sorted(values)
    n = len(s)
    if n == 0:
        return None
    m = n // 2
    return s[m] if n % 2 else 0.5 * (s[m - 1] + s[m])
```

- 窗口大小 `required_frames` 用**奇数**（建议 5），中值无歧义。
- 点/边的中值：对 x、y 分量分别取中值（`_median_point` / `_median_edge`，仿现有 `_mean_point`）。
- 角度量（`axis_yaw_deg` / `axis_angle_px_deg`）：先相对首样本求差、对差值取中值、再加回基准（避免 ±180 绕回污染），仿现有 angle 处理。
- `confidence` 仍可用均值（它本身就是质量指标，不需抗离群）。

验收：构造含 1 个离群帧的 5 帧窗口，median 版 fused 与无离群版偏差 < 噪声 1σ；mean 版会被拉偏 > 3σ（写进单测对照）。

---

## B. 离群拒绝层：修复方向性 bug + 一致性确认（1 天，板端，核心）

重写 `SlotStabilityFilter.add()` 的 gate 逻辑。

### B1. 比较基准：上一帧 → 窗口稳健中心

gate 不再与 `self.samples[-1]`（上一帧本身可能是噪声）比，而是与**当前窗口的中值中心**比。

### B2. 跳变帧：拒绝丢弃，不清窗

```text
若窗口已稳定(len >= required) 且 新帧偏离窗口中值 > gate:
    标记 outlier, consecutive_outlier += 1
    把新帧暂存进 pending_outliers(最多留 K 个)
    不进主窗口, 窗口保持不变
    本周期对外返回: stable=True, 用现有窗口中值(状态没坏)
```

### B3. 一致性确认：区分"真移动"与"散发噪声"

散发噪声 = 跳变帧彼此方向不一致；真移动 = 连续帧都指向同一个新位置。

```text
若 consecutive_outlier >= K_accept (建议 3) 且 这 K 帧彼此互相在 gate 内一致:
    判定为真实大移动 → 接受, 用 pending_outliers 重建窗口, 清 consecutive_outlier
否则只要来一个落回旧窗口附近的正常帧:
    判定散发噪声 → 丢弃 pending, consecutive_outlier 清零, 窗口不动
```

效果：偶发跳一下 → 被拒，状态不坏；车位真的换了/真移动 → 3 帧后被接受跟随。**既抗噪声又不僵死。**

### B4. 静止 vs 运动期的 gate 强度

新增控制器状态传入 filter：`observing_static`（刚下发 STOP/未发运动/在等观察）。

```text
observing_static = True  → gate 收紧(车没动, 大变化必噪声), 例 max_center_shift_cm × 0.5
观测刚结束准备规划       → gate 用常规值
```

gate 阈值来自数据（见 §D），不拍脑袋。

验收：回放注入"单帧跳 30px"序列，B 版无 reject-induced 状态丢失、无 STOP；注入"连续 3 帧一致移动"序列，第 3 帧后窗口跟随到新位置。

---

## C. 丢失容忍层：hold + 宽限期 + 去抖（1 天，板端）

把"丢失"从二值瞬时改成带 coast 与迟滞的状态机。让 filter 统一管理"无检测"周期（主循环把 `acquire_info` 返回 None 也喂给 filter）。

### C1. hold-last（coast）

```text
filter.tick_no_detection(now):
    若有上一稳定 fused 态 且 (now - last_good_ts) <= hold_grace_sec:
        返回 coasted 态: 复制上一稳定 fused, 标记 coasted=True, coast_age_ms
        is_stable 仍 True
    否则:
        进入真丢失 → 交还主循环走 STOP 逻辑
```

### C2. coast 的硬约束（安全攸关，必须写死）

```text
coast 态只能用于:  维持现状判定 / 继续等待观察 / 判 done
coast 态绝不能用于: 发起新的 ARC/MOVE 运动
  → 主循环: if state.get("coasted"): 不进入"选动作并执行"分支, 只 WAIT
  → 终段盲倒 token 是独立机制(已存在), 不受 coast 影响, 保持原样
```

理由：车静止时 coast 旧状态判"现状没变"是安全的；但拿一个"猜的"状态去开车是危险的。这条是 coast 与 dead-reckon 的根本区别。

### C3. STOP 去抖（debounce）——分级，不一刀切

```text
状态质量类门(可去抖, 容忍偶发):
  vision_lost      → 已由 C1 hold 覆盖, grace 内不触发
  divergence       → 连续 M 帧(建议 2)成立才 STOP
  pose_quality 低  → 连续 M 帧才降级

安全攸关门(不去抖或极短, 宁可误停):
  line_risk 压线    → 不去抖(1 帧即停) —— 真实物理危险, 安全优先于平滑
  min_margin < floor→ 不去抖
```

**这是本计划最重要的安全边界**：噪声滤除只放宽"状态质量"类触发，绝不放宽"真实危险"类触发。压线宁可被噪声误停一次，也不能为了平滑而漏停一次。

验收：注入"丢失 0.6s 后恢复"（grace=0.8s）→ 无 STOP、coast 期 WAIT 不发运动；注入"丢失 1.2s" → grace 后正常 STOP；注入"单帧 line_risk" → 立即 STOP（确认未被去抖削弱）。

---

## D. 参数标定（数据驱动，半天，PC，先于 A-C 调阈值）

所有阈值从现有日志的真实噪声分布反推，禁止拍脑袋。

新工具 `tools/perception_noise_profile.py`，输入现有 dry-run / 回归 JSONL，输出：

```text
1. 帧间位移分布: dc 的 p50/p95/p99/max(静止段)  → gate = clamp(p99 × 1.5, 真移动下限)
2. 帧间 yaw 变化分布: 同上                       → yaw gate
3. dropout 长度分布: 连续无检测帧数的直方图 + 最长 → hold_grace_sec = 覆盖 p99 dropout × 1.5,
                                                    但必须 < 终段真盲区时长
4. 单帧离群幅度样本: 最大几个跳变的幅度          → 确认 gate 落在噪声与真移动之间
5. 检测率: 有检测帧/总帧, 按距离分段             → 确认近距离 dropout 是否更频繁
```

产出 `configs/perception_filter.json`：

```json
{
  "schema": "perception_filter.v1",
  "required_frames": 5,
  "gate_center_shift_cm": null,
  "gate_yaw_shift_deg": null,
  "gate_static_scale": 0.5,
  "outlier_accept_consecutive": 3,
  "hold_grace_sec": null,
  "hold_max_frames": null,
  "divergence_debounce_frames": 2,
  "line_risk_debounce_frames": 1,
  "notes": "thresholds derived from <log list>; line_risk 故意不去抖"
}
```

`SlotStabilityFilter` 与主循环从此 json 读参（带 CLI 覆盖 `--perception-filter-json`），不再用散落的硬编码默认。

验收：profile 报告含上述 5 项分布图（文本直方图即可）；json 字段全部由数据填非 null。

---

## E. 落地顺序与回归

```text
D 标定(PC, 半天) → A 中值(板端, 半天) → B 离群修复(板端, 1天) → C 丢失容忍(板端, 1天)
每层独立单测(tools/test_perception_filter.py), 注入构造序列, 不依赖实车
全部完成后: 板端 60s dry-run, 对比改造前后
  - reject_resets 次数应大幅下降(跳变不再清窗)
  - 偶发 dropout 不再产生 STOP
  - 状态稳定性(stable_state_rows / total)应上升
  - line_risk 注入测试确认未被削弱
```

回归通过后，把改造前后 60s dry-run 的稳定率对比写进 `docs/autopark_perception_robustness_20260614.md`。

---

## F. 与现有计划的关系

- 这是 L0/L1 回归的**前置质量改善**：感知更稳 → counter_steer 决策的输入更干净 → 终态更可复现。建议**插在 P0 标定之后、P1 L0 回归之前**做（半天 D + 1.5 天 A/B/C），让 P1 的 5 回合跑在更稳的感知上。
- 不改变 token 盲倒机制、不改变安全门集合、不改变 arm 双门。
- coast（本计划）与 dead-reckon（已默认关闭）是两件事：coast 只维持静止现状、不开车；dead-reckon 会开车、仍受 §C2 约束之外的独立旗标控制。

---

## 一句话总结

```text
跳一下不出问题 = 修 add() 的方向性 bug(拒绝跳变帧而非清窗) + fused 用中值
消失一下不停车 = hold 上一稳定态过宽限期(车静止时物理上安全) + STOP 去抖
不削弱安全     = 压线/越界门不去抖, coast 态只维持不开车
所有阈值       = 从现有日志噪声分布反推, 不拍脑袋
```
