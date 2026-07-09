# Keyboard Feedback Policy Training

## Goal

Train the car to reverse into the parking slot using bounded small steps and
human feedback:

- Right arrow: positive feedback (`+`)
- Left arrow: negative feedback (`-`)
- Space: start a new rollout (`r`)
- `0`: neutral feedback
- `q`: quit

The learner stores a persistent state-action policy on the board:

```text
/opt/parking/autopark/parking_policy.json
```

## Learned State

The board discretizes the current visual parking state:

```text
lon bucket: near / mid / far / very_far
lat bucket: center / left_small / left_large / right_small / right_large
head bucket: straight / yaw_pos_small / yaw_pos_large / yaw_neg_small / yaw_neg_large
```

Example key:

```text
far|right_large|yaw_pos_small
```

## Action Set

Default actions are capped at 7 cm:

```text
MOVE D=-7.0 V=1
ARC D=-7.0 STE=50 V=1
ARC D=-7.0 STE=60 V=1
ARC D=-7.0 STE=70 V=1
ARC D=-7.0 STE=80 V=1
ARC D=-7.0 STE=90 V=1
ARC D=-7.0 STE=100 V=1
ARC D=-7.0 STE=110 V=1
ARC D=-7.0 STE=120 V=1
ARC D=-7.0 STE=130 V=1
```

The learner chooses with epsilon-greedy exploration:

```text
75% exploit current best action
25% explore another safe action
```

## Reward Update

Each action gets a Q score for the current state:

```text
Q <- Q + alpha * (reward - Q)
```

Manual feedback:

```text
right arrow => reward +1
left arrow  => reward -1
0           => reward 0
```

If no manual token is supplied and `--feedback-auto` is enabled, visual deltas
produce an automatic reward.

## Safety

Hard safety limits:

```text
single command |D| <= 7 cm by default
per-rollout training distance <= 70 cm by default, then hold for SPACE/q
STOP after every real movement
vision unstable/lost => STOP
real motion requires --allow-motion, --create-arm-file, --arm, and /tmp/parking_armed
dry-run never sends motion
default training session does not exit by episode count; q quits
```

## Dry Run

Use this first. It accepts keys but does not move the car:

```powershell
.venv\Scripts\python tools\parking_keyboard_policy_trainer.py --episodes 10
```

## Real Training

Run only after confirming the car area is safe:

```powershell
.venv\Scripts\python tools\parking_keyboard_policy_trainer.py --allow-motion --create-arm-file --max-total-cm 70 --max-abs-d-cm 7
```

During training:

```text
RIGHT: the step is closer to the desired route
LEFT : the step is worse or unsafe-looking
SPACE: start a new rollout after repositioning/deciding to reset
0    : neutral feedback
q    : quit immediately
```

## Current Verification

The board controller was deployed to:

```text
/opt/parking/autopark/board_parking_controller.py
```

Dry-run verification confirmed:

```text
actions=10
candidate example: ARC D=-7.0 STE=120 V=1
policy update saved to /tmp/parking_policy_dryrun_7cm.json
send_to_stm32=false
motion_enabled=false
actuator_control_allowed=false
```
