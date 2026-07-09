#!/usr/bin/env python3
"""Prepare OS08A20 intrinsic calibration captures and ROS camera_info YAML."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

try:
    import cv2
    import numpy as np
except ModuleNotFoundError as exc:
    cv2 = None
    np = None
    CV_IMPORT_ERROR = exc
else:
    CV_IMPORT_ERROR = None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def require_opencv() -> None:
    if cv2 is None or np is None:
        raise SystemExit(
            "OpenCV and NumPy are required for this action. "
            f"Import error: {CV_IMPORT_ERROR}"
        )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def chessboard_points(cols: int, rows: int, square_size: float) -> np.ndarray:
    objp = np.zeros((rows * cols, 3), np.float32)
    objp[:, :2] = np.mgrid[0:cols, 0:rows].T.reshape(-1, 2)
    objp *= float(square_size)
    return objp


def detect_chessboard(image: np.ndarray, cols: int, rows: int) -> tuple[bool, np.ndarray | None]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_FAST_CHECK
    ok, corners = cv2.findChessboardCorners(gray, (cols, rows), flags)
    if not ok:
        return False, None
    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30,
        0.001,
    )
    refined = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
    return True, refined


def aruco_module():
    return getattr(cv2, "aruco", None)


def make_charuco_board(
    squares_x: int,
    squares_y: int,
    square_length: float,
    marker_length: float,
    dictionary_name: str,
) -> tuple[Any, Any]:
    aruco = aruco_module()
    if aruco is None:
        raise RuntimeError("cv2.aruco is not available in this OpenCV build")
    dictionary_id = getattr(aruco, dictionary_name, None)
    if dictionary_id is None:
        raise RuntimeError(f"unknown aruco dictionary {dictionary_name}")
    dictionary = aruco.getPredefinedDictionary(dictionary_id)
    if hasattr(aruco, "CharucoBoard"):
        board = aruco.CharucoBoard((squares_x, squares_y), float(square_length), float(marker_length), dictionary)
    else:
        board = aruco.CharucoBoard_create(squares_x, squares_y, float(square_length), float(marker_length), dictionary)
    return aruco, board


def detect_charuco(
    image: np.ndarray,
    squares_x: int,
    squares_y: int,
    dictionary_name: str,
    square_length: float = 1.0,
    marker_length: float = 0.7,
) -> tuple[bool, Any, Any]:
    aruco, board = make_charuco_board(squares_x, squares_y, square_length, marker_length, dictionary_name)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    dictionary = board.getDictionary() if hasattr(board, "getDictionary") else board.dictionary
    detector = aruco.ArucoDetector(dictionary) if hasattr(aruco, "ArucoDetector") else None
    if detector is not None:
        corners, ids, _rejected = detector.detectMarkers(gray)
    else:
        corners, ids, _rejected = aruco.detectMarkers(gray, dictionary)
    if ids is None or len(ids) == 0:
        return False, None, None
    _count, charuco_corners, charuco_ids = aruco.interpolateCornersCharuco(corners, ids, gray, board)
    ok = charuco_ids is not None and len(charuco_ids) >= 4
    return bool(ok), charuco_corners, charuco_ids


def capture(args: argparse.Namespace) -> int:
    require_opencv()
    out_dir = Path(args.output_dir)
    ensure_dir(out_dir)
    cap = cv2.VideoCapture(args.rtsp_url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        print(f"CAPTURE_OPEN_FAILED {args.rtsp_url}")
        return 2

    saved = 0
    seen = 0
    rows: list[dict[str, Any]] = []
    deadline = time.monotonic() + float(args.timeout_sec)
    while saved < args.count and time.monotonic() < deadline:
        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.1)
            continue
        seen += 1
        if seen % max(1, args.frame_stride) != 0:
            continue
        detected = False
        detail = ""
        try:
            if args.pattern == "chessboard":
                detected, _corners = detect_chessboard(frame, args.cols, args.rows)
            else:
                detected, _corners, _ids = detect_charuco(
                    frame,
                    args.charuco_squares_x,
                    args.charuco_squares_y,
                    args.aruco_dictionary,
                    args.charuco_square_length,
                    args.charuco_marker_length,
                )
        except RuntimeError as exc:
            detail = str(exc)

        if args.require_pattern and not detected:
            rows.append({"seen_frame": seen, "saved": False, "detected": False, "detail": detail})
            time.sleep(args.interval_sec)
            continue

        name = f"calib_{saved + 1:04d}_{int(time.time() * 1000)}.jpg"
        path = out_dir / name
        cv2.imwrite(str(path), frame)
        rows.append({
            "seen_frame": seen,
            "saved": True,
            "file": str(path),
            "detected": detected,
            "detail": detail,
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
        })
        print(f"CAPTURE_SAVED {path} detected={detected}")
        saved += 1
        time.sleep(args.interval_sec)
    cap.release()

    manifest = {
        "pattern": args.pattern,
        "rtsp_url": args.rtsp_url,
        "saved": saved,
        "seen_frames": seen,
        "require_pattern": args.require_pattern,
        "rows": rows,
    }
    write_json(out_dir / "capture_manifest.json", manifest)
    print(f"CAPTURE_MANIFEST {out_dir / 'capture_manifest.json'}")
    return 0 if saved > 0 else 3


def calibrate_chessboard(args: argparse.Namespace) -> int:
    require_opencv()
    image_dir = Path(args.image_dir)
    image_paths = sorted(
        p for p in image_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    objp = chessboard_points(args.cols, args.rows, args.square_size)
    objpoints: list[np.ndarray] = []
    imgpoints: list[np.ndarray] = []
    used: list[str] = []
    rejected: list[str] = []
    image_size: tuple[int, int] | None = None

    for path in image_paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            rejected.append(str(path))
            continue
        image_size = (int(image.shape[1]), int(image.shape[0]))
        ok, corners = detect_chessboard(image, args.cols, args.rows)
        if not ok or corners is None:
            rejected.append(str(path))
            continue
        objpoints.append(objp.copy())
        imgpoints.append(corners)
        used.append(str(path))

    if image_size is None or len(objpoints) < args.min_images:
        report = {
            "ok": False,
            "reason": "not_enough_detected_images",
            "required": args.min_images,
            "used_count": len(objpoints),
            "rejected_count": len(rejected),
            "used": used,
            "rejected": rejected,
        }
        write_json(Path(args.report_json), report)
        print(f"CALIBRATION_FAILED {report['reason']} used={len(objpoints)} required={args.min_images}")
        return 4

    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints,
        imgpoints,
        image_size,
        None,
        None,
    )
    report = {
        "ok": True,
        "pattern": "chessboard",
        "image_size": list(image_size),
        "cols": args.cols,
        "rows": args.rows,
        "square_size": args.square_size,
        "rms_reprojection_error": float(rms),
        "used_count": len(used),
        "rejected_count": len(rejected),
        "used": used,
        "rejected": rejected,
        "camera_matrix": camera_matrix.tolist(),
        "distortion_coefficients": dist_coeffs.reshape(-1).tolist(),
        "rvec_count": len(rvecs),
        "tvec_count": len(tvecs),
    }
    write_json(Path(args.report_json), report)
    write_camera_info_yaml(Path(args.output_yaml), image_size, camera_matrix, dist_coeffs.reshape(-1), args.camera_name)
    print(f"CALIBRATION_RMS {rms:.6f}")
    print(f"CAMERA_INFO_YAML {args.output_yaml}")
    print(f"CALIBRATION_REPORT {args.report_json}")
    return 0


def calibrate_charuco(args: argparse.Namespace) -> int:
    require_opencv()
    image_dir = Path(args.image_dir)
    image_paths = sorted(
        p for p in image_dir.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp"}
    )
    aruco, board = make_charuco_board(
        args.charuco_squares_x,
        args.charuco_squares_y,
        args.charuco_square_length,
        args.charuco_marker_length,
        args.aruco_dictionary,
    )
    if not hasattr(aruco, "calibrateCameraCharuco"):
        raise SystemExit("OpenCV aruco.calibrateCameraCharuco is not available in this build")

    all_corners: list[Any] = []
    all_ids: list[Any] = []
    used: list[str] = []
    rejected: list[str] = []
    image_size: tuple[int, int] | None = None

    for path in image_paths:
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None:
            rejected.append(str(path))
            continue
        image_size = (int(image.shape[1]), int(image.shape[0]))
        ok, corners, ids = detect_charuco(
            image,
            args.charuco_squares_x,
            args.charuco_squares_y,
            args.aruco_dictionary,
            args.charuco_square_length,
            args.charuco_marker_length,
        )
        if not ok or corners is None or ids is None:
            rejected.append(str(path))
            continue
        all_corners.append(corners)
        all_ids.append(ids)
        used.append(str(path))

    if image_size is None or len(all_corners) < args.min_images:
        report = {
            "ok": False,
            "pattern": "charuco",
            "reason": "not_enough_detected_images",
            "required": args.min_images,
            "used_count": len(all_corners),
            "rejected_count": len(rejected),
            "used": used,
            "rejected": rejected,
        }
        write_json(Path(args.report_json), report)
        print(f"CALIBRATION_FAILED {report['reason']} used={len(all_corners)} required={args.min_images}")
        return 4

    rms, camera_matrix, dist_coeffs, rvecs, tvecs = aruco.calibrateCameraCharuco(
        all_corners,
        all_ids,
        board,
        image_size,
        None,
        None,
    )
    report = {
        "ok": True,
        "pattern": "charuco",
        "image_size": list(image_size),
        "charuco_squares_x": args.charuco_squares_x,
        "charuco_squares_y": args.charuco_squares_y,
        "charuco_square_length": args.charuco_square_length,
        "charuco_marker_length": args.charuco_marker_length,
        "aruco_dictionary": args.aruco_dictionary,
        "rms_reprojection_error": float(rms),
        "used_count": len(used),
        "rejected_count": len(rejected),
        "used": used,
        "rejected": rejected,
        "camera_matrix": camera_matrix.tolist(),
        "distortion_coefficients": dist_coeffs.reshape(-1).tolist(),
        "rvec_count": len(rvecs),
        "tvec_count": len(tvecs),
    }
    write_json(Path(args.report_json), report)
    write_camera_info_yaml(Path(args.output_yaml), image_size, camera_matrix, dist_coeffs.reshape(-1), args.camera_name)
    print(f"CALIBRATION_RMS {rms:.6f}")
    print(f"CAMERA_INFO_YAML {args.output_yaml}")
    print(f"CALIBRATION_REPORT {args.report_json}")
    return 0


def calibrate(args: argparse.Namespace) -> int:
    if args.pattern == "chessboard":
        return calibrate_chessboard(args)
    return calibrate_charuco(args)


def write_camera_info_yaml(
    path: Path,
    image_size: tuple[int, int],
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
    camera_name: str,
) -> None:
    width, height = image_size
    k = camera_matrix.reshape(-1).tolist()
    d = dist_coeffs.tolist()
    r = np.eye(3, dtype=np.float64).reshape(-1).tolist()
    p = [
        float(camera_matrix[0, 0]), 0.0, float(camera_matrix[0, 2]), 0.0,
        0.0, float(camera_matrix[1, 1]), float(camera_matrix[1, 2]), 0.0,
        0.0, 0.0, 1.0, 0.0,
    ]
    lines = [
        f"image_width: {width}",
        f"image_height: {height}",
        f"camera_name: {camera_name}",
        "camera_matrix:",
        "  rows: 3",
        "  cols: 3",
        "  data: [" + ", ".join(f"{x:.12g}" for x in k) + "]",
        "distortion_model: plumb_bob",
        "distortion_coefficients:",
        "  rows: 1",
        f"  cols: {len(d)}",
        "  data: [" + ", ".join(f"{x:.12g}" for x in d) + "]",
        "rectification_matrix:",
        "  rows: 3",
        "  cols: 3",
        "  data: [" + ", ".join(f"{x:.12g}" for x in r) + "]",
        "projection_matrix:",
        "  rows: 3",
        "  cols: 4",
        "  data: [" + ", ".join(f"{x:.12g}" for x in p) + "]",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)

    cap = sub.add_parser("capture", help="Capture calibration images from the OS08A20 RTSP stream.")
    cap.add_argument("--rtsp-url", default="rtsp://172.20.10.2:554/live0")
    cap.add_argument("--output-dir", default="artifacts/camera_calibration/captures")
    cap.add_argument("--count", type=int, default=20)
    cap.add_argument("--timeout-sec", type=float, default=120.0)
    cap.add_argument("--interval-sec", type=float, default=0.8)
    cap.add_argument("--frame-stride", type=int, default=10)
    cap.add_argument("--pattern", choices=["chessboard", "charuco"], default="chessboard")
    cap.add_argument("--require-pattern", action="store_true", help="Save only frames where the requested target is detected.")
    cap.add_argument("--cols", type=int, default=9, help="Chessboard inner-corner columns.")
    cap.add_argument("--rows", type=int, default=6, help="Chessboard inner-corner rows.")
    cap.add_argument("--charuco-squares-x", type=int, default=7)
    cap.add_argument("--charuco-squares-y", type=int, default=5)
    cap.add_argument("--charuco-square-length", type=float, default=0.04, help="Charuco square length in metres.")
    cap.add_argument("--charuco-marker-length", type=float, default=0.028, help="Charuco marker length in metres.")
    cap.add_argument("--aruco-dictionary", default="DICT_4X4_50")
    cap.set_defaults(func=capture)

    cal = sub.add_parser("calibrate", help="Calibrate from captured chessboard or Charuco images and write ROS camera_info YAML.")
    cal.add_argument("--image-dir", default="artifacts/camera_calibration/captures")
    cal.add_argument("--pattern", choices=["chessboard", "charuco"], default="chessboard")
    cal.add_argument("--cols", type=int, default=9, help="Chessboard inner-corner columns.")
    cal.add_argument("--rows", type=int, default=6, help="Chessboard inner-corner rows.")
    cal.add_argument("--square-size", type=float, default=0.025, help="Chessboard square size in metres.")
    cal.add_argument("--charuco-squares-x", type=int, default=7)
    cal.add_argument("--charuco-squares-y", type=int, default=5)
    cal.add_argument("--charuco-square-length", type=float, default=0.04, help="Charuco square length in metres.")
    cal.add_argument("--charuco-marker-length", type=float, default=0.028, help="Charuco marker length in metres.")
    cal.add_argument("--aruco-dictionary", default="DICT_4X4_50")
    cal.add_argument("--min-images", type=int, default=10)
    cal.add_argument("--camera-name", default="os08a20_camera")
    cal.add_argument("--output-yaml", default="artifacts/camera_calibration/os08a20_camera_info.yaml")
    cal.add_argument("--report-json", default="artifacts/camera_calibration/calibration_report.json")
    cal.set_defaults(func=calibrate)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
