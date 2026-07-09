# L0 收尾 → L1 包络计划（Codex 执行版）- 2026-06-13

> 前置状态：counter_steer 已实现并部署板端、chassis_kinematics 已离线提取、final_pose_report 可量化终态、感知链路健康（检测率 100%、conf 0.72-0.78）。
> 本计划四个阶段：P0 收尾标定（含两个新发现的标定项）→ P1 同起点回归宣告 L0 → P2 维护项清账 → P3 L1 九宫格包络。
> 纪律不变：实车每次一个短动作、安全门全保留、`--arm` + `/tmp/parking_armed` 双门、所有探针留 JSONL 入 `artifacts/autopark_baseline/`。

## 执行状态（Codex 更新）

- P0.T1 已完成：四个 ARC 小距离探针均留档，`D=-3` 在 STE=60/120 两侧都能产生约 1cm 级移动；已写入 `configs/chassis_kinematics.json`：`arc_min_effective_cmd_cm=3.0`、`arc_deadband_cm=1.9`、`coast_after_done_cm=0.8`。
- P0.T3 已完成软件部分：`tools/extract_chassis_kinematics.py` 已增加 `source_log`、`log_date`、`yaw_source_ok`、小距离死区样本剔除、`counter_steer_result` 提取入口；审计报告为 `artifacts/autopark_baseline/chassis_kinematics_audit_20260613.json`。
- P0.T3 当前审计结论：总样本 26，曲率聚合使用 22，剔除 4 条小距离死区探针；未命中 YAW 故障文件名模式；当前 counter-steer 实测样本数为 0。
- P0.T2 已完成：执行 `STE=90/92/94` 三发 `ARC D=-10` 中位探针，当前选择 `servo_center_trim_ste=92`。结果：90 为 `-1.2deg`，92 为 `-0.7deg`，94 为 `-0.8deg`，92 是当前最优实测中位。
- P1 R1 首跑暴露：前三步直退后横向从约 `1.0cm` 增至 `4.6cm`，planner 选择 `ARC D=-6 STE=60` 恢复，但旧 lateral divergence gate 在恢复动作前中止。控制器已改为允许预测安全的横向恢复 ARC：预测横向至少改善 `1cm` 且预测边距至少 `80px` 时，不因 lateral divergence 提前 STOP。
- 已新增默认安全兜底：授权实车流程退出前统一再发一次 `STOP`（`--final-stop-on-exit` 默认开启）。L0/L1 回归默认由海鸥派连续发送每步命令，不使用 `--confirm-each-step`。
- 下一实车项：复位到 L0 起点后，重新做 no-motion precheck，再执行 R1 retry。

---

## P0. 收尾标定（实车，半天，counter_steer 精度的最后三块拼图）

### T1. ARC 小距离死区（counter_steer 距离公式的缺失参数）

反打弧命令距离通常 2~5cm，必须知道 ARC 的最小有效距离与死区。探针序列（每发之间不必复位位姿，任意安全空地即可，记录 DONE D 与后续 STAT D）：

```text
ARC D=-3.0 STE=120 V=1
ARC D=-4.0 STE=120 V=1
ARC D=-4.0 STE=60  V=1     # 左右死区可能不同
ARC D=-3.0 STE=60  V=1     # 时间允许则补
```

判读与写入 `configs/chassis_kinematics.json`：

```json
{
  "arc_deadband_cm": "<命令D与实走差的均值, 预期~2>",
  "arc_min_effective_cmd_cm": "<实走>=1cm 的最小命令距离>",
  "coast_after_done_cm": "<STAT D - DONE D 的均值>"
}
```

counter_steer 距离公式随即更新：`d_cmd = |φ|/deg_per_cm + arc_deadband_cm`，且 `d_cmd ≥ arc_min_effective_cmd_cm`，上限 6.0。预期 Δφ 计算时用 `实走+coast` 而不是命令值。

验收：四发探针数据齐、json 三字段非 null、控制器读取后 smoke test（φ=+4° 案例）打印的 d_cmd 与手算一致。

### T2. 舵机机械中位标定（解释并修正左右弧不对称）

**动机**：当前系数表左右严重不对称（60/120 的 R_eff = 80/100，75/105 = 147/260，软档差 1.76 倍）。最可能解释 = 真实直行中位不在 STE=90。若真实中位 ≈94，则 |60-94|=34° vs |120-94|=26°、|75-94|=19° vs |105-94|=11°，恰好复现观测比值。

探针（不要用 MOVE——MOVE 的 keep_straight 航向保持会掩盖舵机偏置，必须用 ARC 绕过它）：

```text
ARC D=-10.0 STE=90 V=1     # 记录 Δyaw(STAT 前后)
若 |Δyaw| > 1°: 向 Δyaw 减小的方向按 ±2 步进重试 STE=88/92/94...
                直到 |Δyaw| ≤ 0.5°, 该 STE 即机械中位 trim
若 |Δyaw| ≤ 1°: trim=90, 不对称另有原因(记录, 不深究, deg_per_cm 表照用)
```

写入 `chassis_kinematics.json`：`"servo_center_trim_ste": <值>`。下游两个消费者：
1. counter_steer 选档时按"相对 trim 的偏角"判断软硬弧。
2. 直线盲倒若发现系统性侧漂，可把盲倒的 MOVE 换成 `ARC STE=trim`（本计划先不做，记录依据）。

验收：trim 值有探针证据；若 trim≠90，用 trim 重算四档"有效偏角"并在 json 注明。

### T3. 系数表样本来源审计（数据卫生）

**动机**：STE=60 的 n=5 样本可能混入 2026-06-13 上午 YAW 故障窗口（F2/F3 烧录后、用户修复前）的日志，该窗口内 Δyaw 是垃圾。

`tools/extract_chassis_kinematics.py` 增强：
1. 每个样本输出带 `source_log` + `log_date` + `yaw_source_ok` 字段。
2. 排除规则：来自 YAW 故障窗口的日志一律剔除（窗口边界以 `docs/autopark_c0_yaw_validation_20260613.md` 记录为准）。
3. 重算并覆盖 `chassis_kinematics.json` 的 steer_curvature，剔除前后对比写进提取报告。
4. 新增能力：从控制器日志的 `counter_steer_result` 事件中提取样本——**今后每次实车反打自动积累系数样本**。

验收：重算后每档 n 与剔除数有报告；剔除后 deg_per_cm 变化超过 20% 的档位标记"需补实车探针"。

---

## P1. L0 回归：同起点 5 回合完整泊车（实车，半天）

P0 完成后执行。目标：宣告 **L0 里程碑 = 固定起点全自动泊车（停进且平行）**。

### 回合协议

```text
复位:   胶带框复位, dry-run 读 10 帧确认 |slot_x_err_px-基准|<5px 且 |heading-基准|<1°
运行:   action_replanner 实车模式, counter_steer 启用, token 盲倒启用
         必带旗标: --arm + arm file, --counter-steer-enable,
                   --chassis-kinematics-json /opt/parking/autopark/chassis_kinematics.json,
                   --max-motion-steps 8, --max-total-cm 50,
                   --log-jsonl /tmp/parking_l0_regression_r<N>_20260613.jsonl
结束:   final_pose_report 落盘 + 手机拍照一张(俯视尽量)
记录:   初始状态 / 动作序列 / 每动作 counter_steer_decision|result / final_pose_report / 照片
```

### 判定

```text
单回合通过 = final_pose_report.verdict == parked_straight (|final_heading| ≤ 2°) 且深度达标
L0 通过    = 5 回合 ≥ 4 次通过
安全门触发 = 不算失败, 记录后重摆继续(系统自保是正确行为)
连续 3 回合 straighten_failed 或方向打反 = 中止, 回 P0 查 deg_per_cm/符号
```

### 产出

- `docs/autopark_l0_regression_20260613.md`：5 回合逐条记录 + 通过判定 + 失败归因。
- 日志与照片入 `artifacts/autopark_baseline/l0_regression/`。
- **若通过：在 `autopark_long_term_memory.md` 顶部写一行"L0 已达成 (日期)"。**

---

## P2. 维护项清账（半天，与 P1 穿插，不阻塞）

按优先级，均为此前评审遗留：

1. **arm 门收口**（若尚未做）：`board_parking_controller.py` 所有运动发送收口到单一 `send_motion(cmd)`，内部断言 `armed` + steps/total caps，`STOP` 豁免；vision-lost DR 路径与 `pixel_blind_finish` 路径不得绕过。验收：grep 确认运动 `send_cmd` 调用点只剩 `send_motion` 内部一处；不带 `--arm` 跑全部策略的 vision-lost 分支，无任何运动发出。
2. **融合方向位**：`parking_fusion.py` 的 `ds` 方向从 TLM 的 `V` 符号取（D 无符号，前进动作引入前必须修）。验收：构造正/负 V 的 TLM 序列单测，y_s 方向正确。
3. **DONE 缺 YAW 一致性**：固件四条终止路径（DONE/ERR×MOVE/ARC/TIMEOUT/CANCELED）输出字段统一；b2 曾记录一次 `DONE ... D=5.1` 无 YAW。验收：四条路径实测各一次，YAW 字段齐。
4. **响应模型记账**：把已成功的序列（ARC STE=60 修横向、counter_steer 各次、token 盲倒）作为 measured 样本按状态桶写入 `parking_action_response_model.json`。
5. 文档：`autopark_long_term_memory.md` 更新现行流程图（含 counter_steer 相位与 token 规则）。

---

## P3. L1 包络：3×3 起点网格（1-2 天，P1 通过后开工）

### 网格定义

以 L0 标定位姿为中心：

```text
横向偏移: {-5, 0, +5} cm   (胶带框左右平移贴出 3 条基准线)
航向偏移: {-5, 0, +5} °    (量角器或手机水平仪辅助摆角)
= 9 格, 每格 2 回合, 共 18 回合
```

### 每格协议

与 P1 回合协议相同，外加：

```text
回合开始记录格子坐标 (lat_offset, head_offset) 进 JSONL 首条事件
失败归因分类(必填其一):
  gate_no_token      到了终段但 token 门槛过不去(姿态修不到位)
  straighten_failed  反打无效或方向错
  lateral_unreachable 横向修不完(预计出现在 ±5cm 格)
  vision_lost_early  非终段视觉丢失
  safety_stop        其他安全门
  other              附说明
```

### 判定与产出

```text
L1 通过 = ≥7/9 格至少 1/2 回合 parked_straight, 全程无安全违规
成功矩阵: docs/autopark_l1_grid_20260614.md 内 3×3 表格(每格 0/1/2 成功数+失败归因)
```

**矩阵的用途（这是 P3 的真正价值）**：
- `lateral_unreachable` 集中的格子 = `forward_correct`（L2 前进修正）的立项依据与触发条件设计输入。
- `gate_no_token` 集中的格子 = 响应模型在该状态桶缺样本，补桶探针清单从这里生成。
- 全绿 = 直接规划 L2 网格（±15cm/±10°）。

---

## P4. B6 几何预测器（1 天，软件，可与 P3 并行开发、P3 数据后验证）

把评分器对**未实测状态桶**的预测从 `prior_delta` 换成几何计算：

```text
输入: 当前状态 (lateral, heading, y_dist) + 候选动作 (STE, D) + chassis_kinematics
计算: Δφ = (实走预期) × deg_per_cm(STE, 相对trim)
      Δlateral_轴 = R_eff × (1 - cos Δφ) × 方向
      Δ视觉lateral = Δlateral_轴 + y_dist × sin(Δφ) + L_cam × sin(Δφ)   # 杠杆项, L_cam 待 C1 卷尺补量
      Δy = 实走预期 × cos(φ+Δφ/2)
预测优先级: 同桶 measured > 几何计算 > prior(仅 dry-run 排名用)
```

验收：对已有 measured 样本逐条回测，几何预测 vs 实测 delta 偏差 <30%（杠杆项是此前对账差异的主因，必须包含）；T4 回放重跑，动作选择不回归（切换次数仍 ≤2、右偏选右）。

---

## 执行顺序与依赖

```text
P0.T1+T2 (实车, ~8 发探针, 半天) ──► P1 L0 回归 (实车, 半天) ──► P3 L1 网格 (实车, 1-2 天)
P0.T3 (PC, 2 小时) ──┘                                    ┌──► forward_correct 立项(按矩阵)
P2 维护项 (穿插) ──────────────────────────────────────────┤
P4 几何预测器 (软件, 与 P3 并行开发) ──────────────────────┘
```

里程碑口径：P1 过 = **L0 达成**（可对外宣布"固定起点全自动泊车"）；P3 过 = **L1 达成**（横向±5cm/航向±5° 包络内全自动泊车）。
