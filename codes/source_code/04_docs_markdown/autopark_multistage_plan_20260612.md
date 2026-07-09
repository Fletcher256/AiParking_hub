# Autonomous Parking Multi-Stage Plan - 2026-06-12

## Current State

- Camera/YOLO to controller link is working well enough to produce slot polygons, corridor edges, confidence, and JSONL logs.
- STM32 command path is working: recent `SERVO`, `PWM_STAT`, `ARC`, `STAT`, and `STOP` responses show that commands reach the controller.
- The latest instrumented real step sent `ARC D=-6.0 STE=69 V=1`. PWM confirmed the pre-steer command (`ANG=69.0`, `CCR2=1383`) before motion.
- After that one 6 cm reverse arc, visual error worsened: `corridor_x_err_px` changed from `119.91` to `124.56`, and `lat_cm` changed from `-6.51` to `-6.71`.
- Conclusion: the current issue is path/response modeling, not just command delivery. Full parking attempts should pause until steering-response calibration is complete.

## Methods Worth Reusing

The suitable production pattern is not pure reinforcement learning. Mature automated parking stacks separate the problem into perception, planning, and tracking:

- Reeds-Shepp curves: model shortest feasible car paths with forward/backward motion and bounded turn radius. This is the right high-level mental model for parking primitives, but our car should use a simplified small set of reverse arcs first. Source: Pacific Journal of Mathematics / MSP, J. A. Reeds and L. A. Shepp, 1990: https://msp.org/pjm/1990/145-2/pjm-v145-n2-p06-p.pdf
- Hybrid A*: practical autonomous-driving planner that searches over vehicle pose `(x, y, theta)` with continuous-state vehicle updates. This is useful later if we build a real planner; for now it argues that parking must be planned in vehicle pose, not only bbox center error. Source: Dolgov et al., 2008: https://ai.stanford.edu/~ddolgov/dolgov08gppSTAIR.html
- Pure pursuit: robust path tracker that turns a reference path into curvature/steering using a lookahead point. This is useful after we generate a short path, but it is not enough by itself if the reference path is wrong. Source: CMU RI, Coulter, 1992: https://publications.ri.cmu.edu/storage/publications/pub_files/pub3/coulter_r_craig_1992_1/coulter_r_craig_1992_1.pdf
- Modern car-like robot control papers still use the same architecture: path planner generates a feasible reference, motion controller tracks it while respecting steering and velocity constraints. Source: https://arxiv.org/html/2405.06290v1

## Control Logic For This Car

Use a staged controller instead of direct pixel-center chasing:

1. `S0_acquire_and_validate`
   - Require stable YOLO polygon for 3 frames.
   - Require readable `STAT` and `PWM_STAT`.
   - Do not move.

2. `S1_response_calibration`
   - Run one primitive at a time: left arc, right arc, straight.
   - Start at 6 cm, not 20-40 cm.
   - Measure changes in `corridor_x_err_px`, `lat_cm`, heading, and `corridor_min_margin_px`.
   - Promote a primitive only if it improves error without shrinking line margin.

3. `S2_entry_arc`
   - Use the calibrated arc direction to move the car toward the slot entrance.
   - Distance grows from 6 cm to 12 cm, then 20 cm only after repeated improvement.
   - Never continue the same arc if side-line margin is shrinking.

4. `S3_counter_arc`
   - Use the opposite steering direction to straighten before the car loses view of the slot.
   - This stage is needed because the latest failures pressed the car onto the parking frame before target loss.

5. `S4_straight_finish`
   - Only when heading is near slot axis and side margins are stable.
   - Short straight reverse steps.
   - YOLO loss is allowed for only 0.5 s, then `STOP`.

6. `S5_stop`
   - Trigger on target loss, line risk, divergence, cap, abnormal STM32 status, or final pose.

## Software Changes Made

- `tools/board_parking_controller.py`
  - Candidate log semantics were corrected:
    - `send_to_stm32` now means the candidate is expected to be actually sent.
    - Added `motion_gate_open`, `cap_would_stop`, `lateral_would_stop`, and `will_execute_motion`.
  - This prevents future logs from counting a cap-blocked candidate as an executed motion.
  - Added `--strategy primitive_probe` for one-command steering response calibration.

- `tools/parking_response_analyzer.py`
  - New offline analyzer.
  - Pairs each `stm32_motion_result` with the previous and next visual candidate.
  - Reports whether the primitive improved or worsened corridor error, lateral error, and line margin.

- `configs/autopark_multistage_plan.json`
  - New machine-readable plan for safety gates, calibration primitives, and staged parking behavior.

## Next Real Test Plan

Do not run another full parking attempt yet. The next real test should be a bounded calibration run:

1. Place car at the same start pose and ensure steering is physically working.
2. Run one 6 cm left-arc probe.
3. Stop, analyze the log.
4. Reset pose, run one 6 cm right-arc probe.
5. Stop, analyze the log.
6. Choose the entry-arc direction from measured response, then test one 12 cm step.

Only after left/right response is known should we allow 20 cm stage steps or a multi-stage run.
