# YOLO Model Regression Flow - 2026-06-11

The model format is expected to stay the same; only training amount changes.
That means the control interface can remain stable, but output geometry must be
regression-tested.

## Baseline Before Update

Collect:

- RTSP frame or short video
- board YOLO log tail
- `board_parking_controller.py --dry-run` JSONL
- dry-run summary JSON
- dry-run curve CSV

Current baseline directory:

```text
artifacts/autopark_baseline
```

## After Model Update

Run the same dry-run capture and save it as a new JSONL file.

Compare:

```powershell
.venv\Scripts\python tools\parking_model_regression_compare.py --before artifacts\autopark_baseline\parking_dry_run_before.jsonl --after artifacts\autopark_baseline\parking_dry_run_after.jsonl --output artifacts\autopark_baseline\model_regression_compare.json
```

Review:

- detection exists or disappears
- confidence change
- slot center delta
- entrance/axis yaw delta
- `MOVE/ARC/STOP` command family changes
- lateral sign reversal risk

Do not enable automatic motion if:

- lateral sign reverses
- command family changes unexpectedly
- slot center shifts more than a few cm on the same scene
- entrance/axis direction flips

