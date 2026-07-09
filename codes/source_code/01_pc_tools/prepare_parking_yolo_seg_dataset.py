from __future__ import annotations

import json
import os
import random
import shutil
from pathlib import Path


SOURCE_DIR = Path(
    r"D:\parking_board_agent\artifacts\board_training_video"
    r"\yolo_frames_20260627_combined\images"
)
OUT_DIR = Path(
    r"D:\parking_board_agent\artifacts\board_training_video"
    r"\parking_yolo_seg_dataset"
)
CLASS_NAMES = ["Parking"]
VAL_RATIO = 0.1
SEED = 20260627
IMAGE_EXTS = [".jpg", ".jpeg", ".png", ".bmp"]


def normalize_point(x: float, y: float, width: int, height: int) -> tuple[float, float]:
    x = min(max(x / width, 0.0), 1.0)
    y = min(max(y / height, 0.0), 1.0)
    return x, y


def link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def find_image(json_path: Path, data: dict) -> Path | None:
    candidates = []
    image_path = data.get("imagePath")
    if image_path:
        candidates.append(SOURCE_DIR / image_path)
    for ext in IMAGE_EXTS:
        candidates.append(json_path.with_suffix(ext))
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def labels_from_json(json_path: Path) -> tuple[Path, list[str], dict] | None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    image = find_image(json_path, data)
    if image is None:
        return None

    width = int(data["imageWidth"])
    height = int(data["imageHeight"])
    label_lines: list[str] = []
    shape_counts: dict[str, int] = {}

    for shape in data.get("shapes", []):
        label = shape.get("label")
        points = shape.get("points") or []
        shape_type = shape.get("shape_type")
        shape_counts[shape_type] = shape_counts.get(shape_type, 0) + 1

        if label not in CLASS_NAMES or len(points) < 3:
            continue

        values = ["0"]
        for point in points:
            x, y = normalize_point(float(point[0]), float(point[1]), width, height)
            values.extend([f"{x:.6f}", f"{y:.6f}"])
        label_lines.append(" ".join(values))

    if not label_lines:
        return None
    return image, label_lines, shape_counts


def write_data_yaml() -> None:
    yaml_text = "\n".join(
        [
            f"path: {OUT_DIR.as_posix()}",
            "train: images/train",
            "val: images/val",
            "names:",
            *[f"  {i}: {name}" for i, name in enumerate(CLASS_NAMES)],
            "",
        ]
    )
    (OUT_DIR / "data.yaml").write_text(yaml_text, encoding="utf-8")


def main() -> None:
    json_files = sorted(SOURCE_DIR.glob("*.json"))
    samples = []
    shape_counts: dict[str, int] = {}

    for json_path in json_files:
        parsed = labels_from_json(json_path)
        if parsed is None:
            continue
        image, label_lines, per_file_counts = parsed
        samples.append((image, label_lines))
        for key, value in per_file_counts.items():
            shape_counts[key] = shape_counts.get(key, 0) + value

    random.Random(SEED).shuffle(samples)
    val_count = max(1, round(len(samples) * VAL_RATIO))
    splits = {
        "val": samples[:val_count],
        "train": samples[val_count:],
    }

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    for split, split_samples in splits.items():
        for image, label_lines in split_samples:
            image_dst = OUT_DIR / "images" / split / image.name
            label_dst = OUT_DIR / "labels" / split / f"{image.stem}.txt"
            link_or_copy(image, image_dst)
            label_dst.parent.mkdir(parents=True, exist_ok=True)
            label_dst.write_text("\n".join(label_lines) + "\n", encoding="utf-8")

    write_data_yaml()

    summary = {
        "source_dir": str(SOURCE_DIR),
        "out_dir": str(OUT_DIR),
        "classes": CLASS_NAMES,
        "json_files": len(json_files),
        "usable_labeled_images": len(samples),
        "train_images": len(splits["train"]),
        "val_images": len(splits["val"]),
        "shape_counts": shape_counts,
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
