# 倒车泊车控制逻辑框架（纯结构规格，零标定数据）- 2026-06-21

> 本文件只规定**逻辑结构**：状态机、转换条件、动作选择、安全监督、几何约束、收敛性。
> **正文不含任何标定数值**——所有阈值/权重/距离/舵角都用命名符号（如 `LAT_GATE_CM`），集中在 §12 参数表，标"待标定"。
> 数据由独立标定流程填入，本框架与具体数值解耦：参数变了，逻辑不变。
>
> 设计目标：在单目 YOLO + STM32(IMU/里程计/舵机/差速) 条件下，把车从"车位可见的一定初始位姿"可证明地收敛到"停进且平行"的终态。

---

## 0. 三条几何铁律（整个框架的公理，决定所有结构选择）

```text
铁律1 耦合性:   用弧线修横向必然改变航向(弧=转向)。
               → 单条弧无法同时归零横向与航向; 终段必须有显式"反打摆正", 不能靠贪心凑。
铁律2 不可逆性: 修横向要消耗纵深; 越近车位可用纵深越少, 近端横向修不动。
               → 横向必须在远端修完; "横向达标"是进入近端的硬准入门。
铁律3 单源不可信: 所有视觉派生量来自一个 polygon, 会"一致地错"(透视/翻边/局部可见),
               稳定 ≠ 正确。 → 必须用里程计/IMU 交叉校验视觉。
```

派生设计原则：
- **参数与逻辑分离**：正文零数值（§12 表）。
- **安全横切于规划之上**：安全门独立成层，优先级最高，每步每相位无条件执行（§7）。
- **每步只执行一个短动作，执行后停车重观察、重规划**（§8）。
- **联合预测、分相位评分**：每个候选动作预测对全部状态量的影响，权重按相位取（§6）。
- **收敛性可论证**：每个相位维持一个不变量，准入门保证进入下一相位时不破坏前一相位成果（§11）。

---

## 1. 坐标系与状态向量（语义定义，符号化）

### 1.1 坐标系（符号约定待 §12 实验确定，不在此假设正负）

```text
槽坐标系 slot frame:
  原点 = 车位入口边中点
  +Y  = 指向车位内部(倒车前进方向)
  +X  = 沿入口边, 与图像 x 同向
车辆参考点 P = 后轴中点
车辆位姿 (x_s, y_s, φ):
  x_s = P 相对车位中线的横向偏移          (符号 SGN_LAT 待定)
  y_s = P 到入口边的纵向距离(车外为正)     (符号 SGN_Y 待定)
  φ   = 车体倒车运动方向与 +Y 的夹角       (符号 SGN_PHI 待定; 车尾正对入口时 φ=0)
```

### 1.2 状态向量（分四类，按用途）

```text
[度量量 metric]   lateral_cm, dist_cm, heading_deg
                  (= slot_lateral / slot_y_dist / slot_heading_err; 用于几何推理与相位判断)
[像素量 pixel]    x_err_px, left_margin_px, right_margin_px, min_margin_px
                  (用于线边安全; homography 不可信时以像素量为安全主判据)
[质量量 quality]  pose_quality, stable_frames, geom_ok, consistency_ok, vision_age
                  (有效性判据, §2)
[记账量 ledger]   phase, steps_done, total_cm, last_action, last_arc_dir,
                  consec_no_improve, consec_worsened, phase_revisits
                  (状态机/安全门/抗抖动)
```

度量量与像素量的换算依赖 homography，可能不可信 → **安全判据优先用像素量，几何推理用度量量并接受其不确定性**（这也是为什么需要铁律3 的交叉校验）。

---

## 2. 感知有效性层（三重门：稳定 / 合理 / 一致）

输入：一帧 YOLO `mask_polygon`（或"无检测"）。输出：`state_valid: bool` + `state` + `quality`。
**只有三门全过，状态才允许进入规划。** 这是"稳定≠正确"（铁律3）的结构落地。

```text
门1 合理门 GEOM_OK   (绝对几何自洽, 先于一切):
    polygon 面积 ∈ [AREA_MIN, AREA_MAX]
    长宽比 ∈ [AR_MIN, AR_MAX]
    凸性/顶点数合理, 入口边像素长度 ∈ [EDGE_MIN, EDGE_MAX]
    → 挡住"形状本身就错"的检测(局部可见/翻边/碎裂)

门2 稳定门 STABLE_OK (精度, 抗噪声):
    最近 N_STABLE 帧的派生量抖动 < {JIT_LAT, JIT_HEAD, JIT_MARGIN}
    融合用中值(抗离群), 不用均值
    离群帧: 与窗口中值偏差 > GATE_* → 丢弃保窗(不清窗); 连续 K_ACCEPT 帧一致才认定真移动
    → 修正历史 bug: 跳变帧绝不"清窗信新帧"

门3 一致门 CONSIST_OK (正确性, 抗系统偏差):
    动作后用里程计/IMU 传播出"期望视觉状态" predicted_state(§3)
    与实际视觉 measured_state 比较, 偏差 < {CONS_LAT, CONS_HEAD}
    → 不一致 = 这帧视觉可疑(透视/系统偏差), 降权或拒用; 不只是看视觉自身稳不稳
```

视觉丢失（无检测）：
```text
vision_age ≤ HOLD_GRACE_SEC 且 车静止 → hold 上一有效 state, 标 coasted=True
  coasted 态只用于"维持现状判定/继续等待", 绝不发起新运动
vision_age > HOLD_GRACE_SEC          → state_valid=False → 交安全层处理(STOP 或终段 token)
```

---

## 3. 状态估计层（视觉测量 + 里程计先验）

```text
measured_state  = 从有效 polygon 派生的 (lateral, dist, heading, margins, x_err)
predicted_state = 上一步停车态 经里程计 ΔD + IMU Δyaw 传播得到的期望态
                  (传播公式按 §12 的运动学符号; 用于门3 一致校验)
fused_state     = measured_state 经 consistency 校验后采用; 偏差超限时降权/拒用
```

关键区分：**measured 来自视觉（绝对、低频、可能系统性错）；predicted 来自里程计/IMU（相对、高频、不漂但只在一步内可信）。** 一致则互信，不一致则视觉可疑。规划用 fused_state。

---

## 4. 相位状态机（准入门 + 滞回 + 不可逆性）

相位是**单向准入门 + 滞回回退**的有限状态机。每个相位声明它**维持的不变量**和**放行进入下一相位的条件**。准入门编码铁律2（横向不可逆）。

### 4.1 相位定义与不变量

| 相位 | 语义 | 维持的不变量 | 主目标 |
|---|---|---|---|
| `ACQUIRE` | 尚未稳定锁定车位 | 不运动 | 取得稳定有效 state |
| `APPROACH_ALIGN` | 远端：边接近边把横向压到准入阈内 | 纵深充足(`dist > NEAR_DIST`) | **横向收敛**(优先) + 适度推进 |
| `ENTER_CORRIDOR` | 横向已达标，进入走廊推进 | `\|lateral\| ≤ LAT_GATE` 持续 | 推进 + 保持横向 |
| `STRAIGHTEN` | 近端：横向锁定，反打消航向 | `\|lateral\| ≤ LAT_GATE` 且 `dist ≤ NEAR_DIST` | **航向收敛**(反打, 铁律1) |
| `FINAL_REVERSE` | 双零：直倒到深度 | `\|lateral\| ≤ LAT_OK` 且 `\|φ\| ≤ HEAD_OK` | 推进到目标深度 |
| `DONE` | 成功终态 | success 判据持续 `N_DONE` 帧 | 退出 |
| `RECOVER_FORWARD` | (L2) 横向修不完/纵深不够：前进重置 | 前进受限(无前向感知) | 重建可修横向的几何 |
| `ABORT/HOLD` | 横切：安全门触发 | 停止 | 等人工/安全退出 |

### 4.2 转换规则（准入门，带滞回）

```text
ACQUIRE → APPROACH_ALIGN:        state_valid 持续 N_LOCK 帧
APPROACH_ALIGN → ENTER_CORRIDOR: |lateral| ≤ LAT_GATE 且 stable   (★铁律2 准入门)
ENTER_CORRIDOR → STRAIGHTEN:     dist ≤ NEAR_DIST 且 |lateral| ≤ LAT_GATE
STRAIGHTEN → FINAL_REVERSE:      |φ| ≤ HEAD_OK 且 |lateral| ≤ LAT_OK
FINAL_REVERSE → DONE:            success 判据(§9)持续 N_DONE 帧

回退(带滞回, 防抖):
  任何近端相位 若 |lateral| > LAT_GATE + HYST_LAT → 回退到 APPROACH_ALIGN
  STRAIGHTEN/FINAL 若 dist 异常增大(误检) → 回退并重锁
  回退累计次数 > MAX_REVISIT → 触发 ABORT(防 align↔straighten 震荡)

L2 扩展:
  APPROACH_ALIGN 若 横向修正方向纵深不足(预测无单弧可改善横向且不压线)
    → RECOVER_FORWARD (前进重置几何), 受 §7 前进限额; 完成后回 APPROACH_ALIGN
```

滞回（`HYST_*`）保证转换不在边界抖动。准入门保证：**进入近端时横向已达标，且近端相位维持横向不变量** → 近端"修不动横向"不再是问题（铁律2 被结构尊重）。

---

## 5. 动作生成与候选集（参数化模板，按相位裁剪）

动作是**参数化模板**，不写死数值。方向语义全部相对 `STE_STRAIGHT`（实测 Δyaw≈0 的直行舵角），**不假设直行=90/100、不假设左右对称**（解决上一轮 STE=100/不对称问题）。

```text
REVERSE_STRAIGHT(d)           舵角=STE_STRAIGHT, 倒车直行
REVERSE_ARC(d, side, mag)     倒车弧; side∈{L,R}, mag∈{soft,hard};
                               实际舵角 = STE_STRAIGHT ± offset(side,mag), offset 各侧各档独立标定
COUNTER_ARC(d, side, mag)     反打弧(STRAIGHTEN 专用); side = 抵消当前 φ 的方向
FORWARD_CORRECT(d[, side])    (L2)前进修正; 无前向感知 → 纯里程, 严格限额(§7)
WAIT / STOP                   控制器内建, 不入动作库
```

每个相位的**允许动作集**（体现"该相位该干什么"，配合 §4 不变量）：

```text
APPROACH_ALIGN:  REVERSE_ARC(任意 side/mag), REVERSE_STRAIGHT, [RECOVER_FORWARD]
ENTER_CORRIDOR:  REVERSE_STRAIGHT, REVERSE_ARC(soft, 仅小幅保横向)
STRAIGHTEN:      COUNTER_ARC, REVERSE_STRAIGHT
FINAL_REVERSE:   REVERSE_STRAIGHT (+ 终段视觉盲区时一次性 token, §8.3)
```

距离 `d` 的取值：受该动作的最小有效距离 `ARC_MIN`/`MOVE_MIN`（死区）下限、单步上限 `STEP_MAX`、剩余纵深、剩余总距离约束（数值见 §12）。

---

## 6. 预测与评分（联合 + 分相位权重 + 预测终态）

### 6.1 预测（每个候选动作 → 预测完整下一状态）

```text
predict(action, state) → (lateral', dist', heading', min_margin', line_risk')
预测来源优先级:
  1. 同状态桶 measured 响应(若有)
  2. 几何模型(用 STE→曲率 + 距离尺度推算; 含相机杠杆项 lateral 修正)
  3. prior(仅 dry-run 排名; 实车不据此自动执行)
```

预测必须输出**全部**状态量（不能只预测一个）——这是联合评估的前提（解决铁律1：要看到一个动作对横向和航向的同时影响）。

### 6.2 评分（加权代价，权重按相位）

```text
cost(action) =  W_LAT[phase]    * |lateral'|
              + W_HEAD[phase]   * |heading'|
              + W_PROGRESS[phase]* progress_penalty(dist')
              + W_MARGIN        * margin_shortfall(min_margin')
              + W_STEER         * |steer - STE_STRAIGHT|       (大舵角轻惩)
              + W_SWITCH        * switch_penalty(action, last_arc_dir)   (换向惩罚, 抗抖)
score = -cost; 选 score 最大者
```

**分相位权重**（解决缺陷 F；只给相对关系，数值见 §12）：
```text
APPROACH_ALIGN:  W_LAT 主导,  W_PROGRESS 次之, W_HEAD 小
ENTER_CORRIDOR:  W_PROGRESS 主导, W_LAT 保持
STRAIGHTEN:      W_HEAD 主导(终段航向决定停得正不正), W_LAT 锁定
FINAL_REVERSE:   W_HEAD + W_MARGIN 主导
```

### 6.3 硬淘汰（直接出局，不参与排名）

```text
预测 line_risk 触发                         → 淘汰
预测 min_margin' < MARGIN_FLOOR             → 淘汰
action 不在当前相位允许集                    → 淘汰
实车模式 且 action 未标定(无 measured 桶且非中性直行) → 淘汰(只能走标定流程)
```

### 6.4 抗抖动 / 防不收敛

```text
换向惩罚:   候选与上一弧反向 → 加 W_SWITCH (抑制左右来回打)
保持滞回:   上一动作仍合法且分差 < EPS_HOLD → 保持上一动作
连败熔断:   同动作连续 CONSEC_WORSE 次实测 worsened → 本回合禁用该动作 + STOP
进度看门狗: 连续 CONSEC_NOIMPROVE 步 横向与深度均无显著改善 → STOP(stalled)
divergence: 用"预测终态是否改善"判, 不用瞬时值(弧修横向非单调) (解决缺陷 F)
```

---

## 7. 安全监督层（横切，优先级最高，独立于规划）

**安全门是横切关注点，每步每相位无条件执行，优先于动作选择。** `line_risk` 在此层，**不是相位**（修正上一轮缺陷 D）。

```text
G1  双 arm 门:      无 --arm 或 无 arm-file → 不运动
G2  dry-run:        dry-run 永不发运动
G3  唯一出口:        所有运动命令经 send_motion(); 安全断言在此一处; 任何分支不得旁路
G4  视觉丢失:        vision_age > HOLD_GRACE → STOP (终段例外见 §8.3 token)
G5  压线/边距:       line_risk 或 min_margin < MARGIN_FLOOR → 立即 STOP(不去抖, 安全优先)
G6  状态发散:        预测终态发散 / consec 异号 → STOP
G7  连败熔断:        §6.4 → STOP
G8  距离/步数上限:    total_cm > TOTAL_MAX 或 steps > STEP_MAX_N → STOP
G9  STM32 异常:      ACK/DONE/ERR/STAT 异常或超时 → STOP
G10 退出兜底:        进程任何退出路径 → 再发一次 STOP
G11 状态无效:        state_valid=False 且非终段 token → 不运动
```

分级原则：**安全攸关门(G5)不去抖、宁可误停；状态质量门(G4/G6)可带 grace/去抖**。

---

## 8. 执行与重观察循环（主循环）

### 8.1 单步时序

```text
loop:
  state = perceive()                      # §2 三重门 + §3 估计
  if not safe_preconditions(): handle_safety(); continue        # §7 横切, 最先
  phase = update_phase(state, phase)      # §4 准入门 + 滞回
  if phase == DONE: send STOP; exit(parked)                     # §9
  candidates = generate(phase)            # §5 按相位裁剪
  scored = [ (a, score(a, predict(a,state))) for a in candidates if not hard_cull(a) ]   # §6
  action = argmax(scored)  (with hysteresis/switch rules)
  if action in {WAIT, none_eligible}: settle(); continue
  if not safety_gate(action): handle_safety(); continue         # §7 再核一次
  send_motion(action)                     # §G3 唯一出口
  wait_done()                             # 等 STM32 DONE/ERR
  read_odom_imu()                         # 记 ΔD, Δyaw → §3 predicted_state
  settle_until_still()                    # 等车停稳(VEL→0 且 X/Y/D 不再变), 非固定 sleep
  ledger_update(delta, verdict, consistency)   # 记账 + 连败/进度看门狗
  # 回到 loop 顶部重新观察(动作后 reset 视觉窗口, 由 §2 重新攒稳定 + 一致校验)
```

### 8.2 停稳与观察的正确性约束

```text
- 必须等车真停稳再读视觉(车动时视觉/里程计都在变, 位姿是糊的)。停稳判据 = 实测(VEL≈0 且里程不变), 非固定延时。
- 动作后 reset 视觉窗口, 但第一帧起即走 §2 三重门; 用 §3 predicted_state 做一致校验, 防"动作后近端系统偏差被当成稳定真值"。
```

### 8.3 终段视觉盲区（一次性 token，受控例外）

```text
进入 FINAL_REVERSE 后若视觉进入盲区(车位太近出视野):
  仅当最近一次有效态满足 (|lateral| ≤ LAT_OK 且 |φ| ≤ HEAD_OK 且 margin 安全) → 写一次性 token
  token 允许一条 REVERSE_STRAIGHT(d_blind), d_blind = 剩余深度 + 死区补偿(§12), 上限 BLIND_MAX
  执行即 STOP 即标 consumed; 禁止连续盲倒; 不满足门槛不写 token(退回先修姿态)
```

---

## 9. 终止判定（DONE / ABORT）

```text
SUCCESS (→DONE, 正常退出):
  |lateral| ≤ LAT_OK 且 |φ| ≤ HEAD_OK 且 dist ≤ DEPTH_TARGET 且 min_margin ≥ MARGIN_OK
  且 上述持续 N_DONE 帧
ABORT (安全中止, 记录原因):
  任一安全门(§7) / 连败熔断 / 进度看门狗 / 回退超限 / 总距离超限
  归因分类: line_risk | margin_floor | stalled | diverged | lateral_unreachable
            | vision_lost | straighten_failed | stm32_error | cap_exceeded
退出一律先发 STOP(G10)。
```

**没有"到了近端就停"——必须 success 判据满足才算成功**（解决缺陷 E）。

---

## 10. 模块化（实现映射，便于单测，不绑死文件名）

各层应为**独立可单测的纯函数**，状态在外层传递：

```text
perception_gate(polygon, window) -> (state_valid, state, quality)     # §2
estimate(measured, predicted)    -> fused_state                       # §3
phase_machine(state, phase, ledger) -> phase'                         # §4
generate_candidates(phase)       -> [action]                          # §5
predict(action, state, model)    -> next_state                        # §6.1
score(action, next_state, phase) -> cost                              # §6.2-6.4
safety_monitor(state, action, ledger) -> (ok, reason)                 # §7  (横切, 最高优先)
send_motion(action)              -> ack/done   (唯一运动出口)          # §G3
```

主循环（§8）只编排这些纯函数。规划层与安全层分离：安全层可独立否决规划层任何输出。

---

## 11. 收敛性论证（为什么这套逻辑能"停正停进"）

用相位不变量串成一条收敛链——这是本框架"正确"的核心，与参数无关：

```text
1. APPROACH_ALIGN: 评分以 W_LAT 主导 → 横向单调收敛; 纵深充足故有空间修。
   准入门要求 |lateral| ≤ LAT_GATE 才放行 → 进入近端时横向必达标。 (铁律2 被尊重)
2. ENTER_CORRIDOR: 不变量 |lateral| ≤ LAT_GATE 持续; 主推进。
   回退门: 横向越界即退回 step1 → 横向成果不被破坏。
3. STRAIGHTEN: 横向已锁定(不变量), 用 COUNTER_ARC 收敛航向。
   反打弧的横向副作用受 |lateral| 不变量 + 回退门约束, 不会把横向带出界。 (铁律1 被结构处理)
4. FINAL_REVERSE: 此时 |lateral| ≤ LAT_OK 且 |φ| ≤ HEAD_OK (双零), 直倒不再引入误差。
5. DONE: success 判据是双零+深度+margin 的合取, 持续 N_DONE 帧才宣告。
```

每个准入门保证"进入下一相位时，前一相位的成果（不变量）成立且后续不破坏它"。因此整条链把任意合法初始态单调推向双零终态；任何环节无法推进（无可行动作/发散/卡住）都由安全层截停而非继续恶化。**这条链的成立不依赖任何具体数值——数值只影响收敛速度和可达初始范围(能力等级)，不影响逻辑正确性。**

---

## 12. 参数表（全部待标定；正文用符号，此处给语义/量纲/标定法，不赋值）

| 符号 | 语义 | 量纲 | 所属 | 标定方法 |
|---|---|---|---|---|
| `SGN_LAT/SGN_Y/SGN_PHI` | 三个坐标符号约定 | — | §1 | 摆位/手动旋转实验定符号 |
| `STE_STRAIGHT` | 直行舵角(Δyaw≈0) | deg | §5 | `ZERO_YAW` 后 `ARC D=-K` 扫舵角找 Δyaw≈0 |
| `offset(side,mag)` | 各侧各档弧的舵角偏移 | deg | §5 | 每侧每档独立标定，不假设对称 |
| `STE→曲率 / deg_per_cm / R_eff` | 各舵角的转弯响应 | deg/cm,cm | §6.1 | 每档 ARC 实测 Δyaw/ΔD |
| `ARC_MIN/MOVE_MIN` | 最小有效命令距离(死区) | cm | §5 | 小距离探针扫到实走≥1cm |
| `*_deadband/coast` | 命令-实走差、停后滑行 | cm | §6.1/§8.3 | 命令vs DONE.D vs STAT.D |
| `L_cam` | 相机光心到后轴纵距 | cm | §6.1 | 卷尺 |
| `LAT_GATE` | 进入近端的横向准入阈 | cm | §4 | 由车位/车宽余量定 |
| `LAT_OK/HEAD_OK/DEPTH_TARGET/MARGIN_OK` | success 判据 | cm/deg/cm/px | §9 | 由"停进且平行"的几何定 |
| `NEAR_DIST` | 近端起始深度 | cm | §4 | 由可用纵深定 |
| `MARGIN_FLOOR` | 压线急停边距 | px | §7 | 由车体到线最小安全定 |
| `HYST_*` | 各相位滞回带 | 同被滞回量 | §4 | 略大于噪声 |
| `N_STABLE/K_ACCEPT/N_LOCK/N_DONE` | 各帧计数门 | 帧 | §2/§4/§9 | 由帧率与噪声定 |
| `JIT_*/GATE_*/CONS_*` | 稳定/离群/一致阈 | 同被判量 | §2 | 由噪声分布(3σ)反推 |
| `AREA_*/AR_*/EDGE_*` | polygon 合理性范围 | px²/—/px | §2 | 由正常车位检测分布定 |
| `HOLD_GRACE_SEC` | 视觉丢失宽限 | s | §2/§7 | 覆盖偶发丢帧、短于真盲区 |
| `STEP_MAX/BLIND_MAX/TOTAL_MAX/STEP_MAX_N` | 单步/盲倒/总距/总步上限 | cm/cm/cm/步 | §5/§7/§8.3 | 安全裕量定 |
| `W_LAT[phase]/W_HEAD[phase]/W_PROGRESS[phase]/W_MARGIN/W_STEER/W_SWITCH` | 分相位评分权重 | — | §6.2 | 先按§6.2相对关系设，回放调 |
| `EPS_HOLD/CONSEC_WORSE/CONSEC_NOIMPROVE/MAX_REVISIT` | 抗抖/熔断/看门狗 | —/次/步/次 | §6.4/§4 | 经验+回放定 |

**框架与数据的契约**：数值改变只改变收敛速度与可达初始范围（能力等级 L0→L2），不改变 §11 的收敛逻辑。任何一个符号必须有单一可信源（一处定义、各处引用），杜绝代码/配置/模型对同一量给出不同值。

---

## 13. 本框架如何修正既往结构缺陷（对照）

```text
缺陷A 横向-航向耦合     → §4 STRAIGHTEN 相位 + §5 COUNTER_ARC + §11 收敛链 step3
缺陷B 横向不可逆性     → §4 LAT_GATE 准入门(APPROACH→ENTER) + 回退门
缺陷C 稳定≠正确        → §2 门3 一致校验 + §3 predicted_state(里程计/IMU 校验视觉)
缺陷D line_risk 错当相位 → §7 G5 归安全门; §4 相位表无 line_risk 节点
缺陷E 缺 done 判定      → §9 success 合取判据 + 持续帧
缺陷F 瞬时 divergence/固定权重 → §6.4 预测终态判 divergence + §6.2 分相位权重
旁路风险(STE 硬编码等)  → §5 方向全相对 STE_STRAIGHT + §6.3 未标定淘汰 + §G3 唯一出口 + §12 单一可信源
```
```
