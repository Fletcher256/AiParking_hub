# 节奏感计划：缩短步间停顿 + 演示节拍（Codex 执行版）- 2026-06-13

> 目标：让"阶段倒车"从"移动 2-4s → 停顿 3.5-4.5s（不规律）"变成"移动 → 短促均匀停顿（~0.5-0.8s）"，达到演示用的有节奏感的阶段倒车。
> 原则：**只砍软件浪费，不砍物理必要的停稳与观察**。改动集中在 `board_parking_controller.py` 串口层与每步执行 helper，纯标准库。安全门、arm 双门、token 机制全部不动。

---

## 0. 根因量化（源码核实，2026-06-13）

每步（action_replanner 执行段 `:4055-4090`，另一份相同模式在 `:1940-1984`）的串口往返序列：

```text
read_stat(pre)  →  SERVO(可选)  →  TEL ON  →  动作命令  →  TEL OFF  →  read_stat(post)  →  sleep(settle)
   send_cmd          send_cmd      send_cmd    send_cmd     send_cmd      send_cmd
```

= **6 次 send_cmd**。每次 `send_cmd`（`:548`）开头固定 drain（`:555`，`end=now+0.4`，`os.read` 循环读到 0.4s 满）：

| 每步开销项 | 当前耗时 | 必要性 |
|---|---|---|
| 6 × drain 0.4s | **2.4s** | ❌ 纯浪费（清缓冲，与车无关） |
| 2 × STAT 往返 | ~0.4-0.8s | ⚠️ 多数可省（DONE 已带 X/Y/D/YAW） |
| TEL ON/OFF × 2 | drain 已计 + 往返 | ⚠️ 可改 session 级常开 |
| settle_sec | 0.6s | ✅ 部分必要（等停稳），但可实测下调 |
| 重新攒稳定帧 | 0.5-1.5s | ✅ 必要（观察），但可优化 |
| 动作执行本身 | 2-4s | ✅ 物理必要 |

**非移动停顿 ≈ 2.4(drain) + 0.6(settle) + 0.6(STAT) + 观察 ≈ 4s，其中 ~3s 是纯软件浪费。**

---

## 第 0 步（P0，必做先行）：插桩量化，先测后砍

禁止凭估算猛砍。先给每步执行 helper 加计时，JSONL 记 `step_timing` 事件：

```json
{"event": "step_timing", "step": 1,
 "t_drain_total_ms": 0, "t_pre_stat_ms": 0, "t_servo_ms": 0,
 "t_tel_ms": 0, "t_move_cmd_ms": 0, "t_post_stat_ms": 0,
 "t_settle_ms": 0, "t_observe_to_stable_ms": 0,
 "t_step_total_ms": 0, "t_move_only_ms": 0, "t_idle_ms": 0}
```

验收：板端跑一次 3-4 步泊车，拿到真实分解。后续每项砍完用同一字段对照前后。**这是节奏感工作的度量基准。**

---

## A. 消除 drain 浪费（P0，最大收益 ~2s/步）

drain 的目的是丢弃上一条响应的残留字节，防止污染本条解析。现状用 0.4s 死等，过度。两种修法，**选 A2（更稳）**：

### A1（保底）drain 改快速 flush
把固定 0.4s 改为"一次非阻塞读清空即返回"，上限 0.05s。省 ~0.35s × 6。

### A2（推荐）seq 对齐，根本上不依赖 drain
命令已带 `@seq`，固件 DONE/ERR/STAT 也回带 seq（`DONE <seq> ...`）。`send_cmd` 改为：

```text
发 @seq cmd → 读行 → 只接受行内 seq == 本次 seq 的 DONE/ERR(STAT 同理)
            → 旧 seq 的残留行直接跳过(它们就是 drain 想丢的东西)
drain 缩到一次非阻塞 flush(≤0.05s) 或完全去掉
```

好处：既省 2s，又比 drain **更可靠**（杜绝"把上一条 DONE 当本条"的误判，这是当前 drain 在掩盖的潜在 bug）。

验收：seq 匹配单测（构造含旧 seq 残留 + 本 seq DONE 的字节流，确认只认本 seq）；板端连发 5 条命令无错配；step_timing 的 `t_drain_total_ms` 降到 <300。

---

## B. 砍冗余串口往返（P0，~1s/步）

### B1. 省掉 post read_stat
F3 已让 DONE 带 `X/Y/D/YAW`。动作后**直接解析 DONE 行**拿末态，不再单独 `read_stat()`。
- 前置依赖：DONE 字段一致性（b2 曾记录一次 DONE 缺 YAW）。先确认四条终止路径字段齐（= L1 计划 P2.3）。
- 回退：若 DONE 解析缺字段，再 fallback 到一次 STAT（不是默认路径）。

### B2. TEL 改 session 级常开
演示/连续模式下，session 开始 `TEL ON` 一次、结束 `TEL OFF` 一次，**不每步切换**。每步省 2 次 send_cmd。
- 新增 `--telemetry-session-mode`（默认 off 保持现状）。开启时每步只在内存里按动作时间窗切分 TLM。

### B3. pre read_stat 按需
action_replanner 每步开头的 `read_stat(pre)`：若上一步已从 DONE 拿到末态、且本步规划只需视觉状态（已从 UDP 有），则跳过。仅在 session 首步或异常后读一次。

验收：step_timing 显示每步 send_cmd 次数从 6 降到 2-3（动作 + 必要 STAT）；总 idle 时间对照下降。

---

## C. settle 与观察实测下调（P1，~0.5-1s/步）

### C1. settle_sec 实测定值
6cm V=1 低速，停稳快。用 step_timing + 连续 STAT 测"DONE 后多久 VEL 归零且 X/Y/D 不再变" = 真实停稳时间。settle 设为该值 + 小裕量（预期可从 0.6 降到 0.2-0.3）。**不可设 0**：车没停稳读 YOLO 位姿是糊的。

### C2. 观察攒帧
配合感知滤波计划（中值 + 抗离群），`stable_frames` 从 5 降到 3，重新攒稳定的时间减半。**依赖感知鲁棒性计划先落地**，否则降帧数会增加误判。

验收：C1 有停稳时间实测曲线；C2 在感知计划完成后做，回归确认降帧数不增加误动作。

---

## D. 演示节拍模式（P1，把"短"变成"有节奏"）

节奏感 ≠ 无停顿。阶段倒车的"移动—顿—移动"节拍本身是好看的，关键是**停顿短、均匀、可预期**。A-C 把停顿砍短后，加一个可选节拍钳制：

```text
--demo-cadence-sec T   (默认 0=关)
  每步总时长(从动作发出到下一步发出)钳到固定节拍 T:
    若该步实际用时 < T → 补足到 T(均匀停顿)
    若 > T → 不延长(安全优先, 不为节拍牺牲观察)
  推荐 T 由 A-C 完成后实测的"最长正常步时长 + 小裕量"决定, 预期 1.5-2.0s/步
```

效果：每步等长节拍，视觉上像"咔、咔、咔"的整齐阶段倒车，而非长短不一的卡顿。

验收：开启后连续 4-5 步，step_timing 的 `t_step_total_ms` 方差显著下降（均匀）；关闭时行为同现状。

---

## E. 统一执行 helper（贯穿 A-D，与 P2.1 send_motion 收口合并）

当前每步时序逻辑在 `:1940` 与 `:4055` 两处重复。借本次重构**收口成单一 `exec_one_motion(cmd, ...)`**：内部统一 seq 对齐发送、DONE 解析末态、可选 TEL、settle、step_timing 记录。同时满足 L1 计划 P2.1 的"运动发送收口到 send_motion"安全要求（arm 断言 + caps 在此一处）。

验收：grep 确认运动命令发送只剩 `exec_one_motion` 一处；两段执行路径行为一致（回归 dry-run 日志对照）。

---

## 安全权衡（红线，不可越）

```text
可砍(软件浪费):  drain 死等、冗余 STAT、每步 TEL 切换、过大超时默认值
不可砍(物理必要): 停稳时间(settle 下限由实测定, 不为节奏归零)
                  停稳后再读位姿(车动时 YOLO/里程计是糊的)
不可削弱:        arm 双门、压线/越界安全门、token 一次性机制
正确性前提:      seq 对齐必须单测过(替代 drain 后不能误把旧响应当本条)
                 省 STAT 依赖 DONE 字段完整(先修 DONE 一致性)
```

---

## 落地顺序与预期效果

```text
第0步 插桩 step_timing (板端, 1h) ── 拿到基准
  ↓
A seq对齐去 drain (1天, 含单测)        −2.0s/步
B 省冗余 STAT + TEL 常开 (半天)        −1.0s/步
C settle/观察实测下调 (半天, C2 依赖感知计划)  −0.5~1s/步
D demo-cadence 节拍 (半天)            停顿均匀化
E exec_one_motion 收口 (贯穿, 合并 P2.1 安全收口)
  ↓
预期: 步间停顿 4s → 0.5-0.8s, 每步节拍均匀 ~1.5-2s, 阶段倒车连贯有节奏
```

与 L1 计划的关系：A/B/E 同时清掉 P2.1 安全收口与 P2.3 DONE 一致性两项遗留；C2 依赖感知鲁棒性计划。建议在 P1 L0 回归**之前**做完 A/B（让回归本身就跑得连贯、好录演示），C/D 可在 L0 达成后为演示打磨。
```
