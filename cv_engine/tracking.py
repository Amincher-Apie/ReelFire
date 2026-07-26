"""ByteTrack 目标跟踪 + 运动轨迹绘制模块。

用法:
    python -m cv_engine.tracking --video path/to/video.mp4 --model models/custom.pt
    python -m cv_engine.tracking --video path/to/video.mp4 --output outputs/tracking.mp4
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

from cv_engine.yolo_detector import YoloDetector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="目标跟踪与轨迹绘制")
    parser.add_argument("--video", type=Path, required=True, help="输入视频路径")
    parser.add_argument("--model", type=Path, default=Path("models/yolo11n.pt"), help="YOLO 模型权重")
    parser.add_argument("--output", type=Path, default=None, help="输出视频路径")
    parser.add_argument("--trajectory-output", type=Path, default=None, help="轨迹 JSON 输出路径")
    parser.add_argument("--conf", type=float, default=0.35, help="检测置信度阈值")
    parser.add_argument("--tracker", type=str, default="bytetrack.yaml", help="跟踪器配置文件: bytetrack.yaml / botsort.yaml")
    parser.add_argument("--show", action="store_true", help="实时显示跟踪画面")
    return parser.parse_args()


def _get_tracker(tracker_type: str) -> str:
    """根据类型返回跟踪器配置文件名，ultralytics 内置支持 bytetrack 和 botsort。"""
    valid = {"bytetrack", "botsort", "bytetrack.yaml", "botsort.yaml"}
    if tracker_type not in valid:
        raise ValueError(f"不支持的跟踪器: {tracker_type}，可选: bytetrack / botsort")
    # 自动补全 .yaml 后缀
    if not tracker_type.endswith(".yaml"):
        tracker_type += ".yaml"
    return tracker_type


def track_video(
    video_path: Path,
    model_path: Path,
    tracker_type: str = "bytetrack",
    confidence_threshold: float = 0.35,
    output_path: Path | None = None,
    trajectory_output_path: Path | None = None,
) -> dict:
    """对视频进行目标跟踪，返回轨迹数据和统计信息。"""
    detector = YoloDetector(str(model_path), confidence_threshold)
    tracker_name = _get_tracker(tracker_type)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"无法打开视频: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    writer = None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(str(output_path), fourcc, fps, (width, height))

    trajectory_data: dict[int, list[dict]] = {}
    frame_results = []
    frame_index = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        results = detector.model.track(
            source=frame,
            conf=confidence_threshold,
            tracker=tracker_name,
            verbose=False,
            persist=True,
        )

        annotated = frame.copy()

        for result in results:
            if result.boxes is None:
                continue

            boxes = result.boxes
            track_ids = boxes.id

            if track_ids is None:
                continue

            for i, track_id in enumerate(track_ids.tolist()):
                x1, y1, x2, y2 = [float(v) for v in boxes.xyxy[i].tolist()]
                conf = float(boxes.conf[i])
                cls_id = int(boxes.cls[i])
                cls_name = detector.model.names[cls_id]

                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)

                if track_id not in trajectory_data:
                    trajectory_data[track_id] = []
                trajectory_data[track_id].append({
                    "frame": frame_index,
                    "timestamp": round(frame_index / fps, 3) if fps > 0 else 0.0,
                    "center": [cx, cy],
                    "bbox": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                    "class": cls_name,
                    "confidence": round(conf, 4),
                })

                color = _track_id_to_color(track_id)
                cv2.rectangle(annotated, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
                cv2.putText(
                    annotated,
                    f"ID{track_id} {cls_name} {conf:.2f}",
                    (int(x1), int(y1) - 8),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    color,
                    1,
                    cv2.LINE_AA,
                )

                cv2.circle(annotated, (cx, cy), 3, color, -1)

        if writer:
            writer.write(annotated)

        frame_results.append({
            "frame": frame_index,
            "timestamp": round(frame_index / fps, 3) if fps > 0 else 0.0,
            "detection_count": len([
                tid for tid in trajectory_data
                if trajectory_data[tid] and trajectory_data[tid][-1]["frame"] == frame_index
            ]),
        })

        frame_index += 1

    cap.release()
    if writer:
        writer.release()

    if trajectory_output_path:
        trajectory_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(trajectory_output_path, "w", encoding="utf-8") as f:
            json.dump(trajectory_data, f, ensure_ascii=False, indent=2)

    return {
        "total_frames": frame_index,
        "total_tracks": len(trajectory_data),
        "video_info": {
            "fps": fps,
            "width": width,
            "height": height,
            "duration": round(frame_count / fps, 3) if fps > 0 else 0.0,
        },
        "trajectory_output": str(trajectory_output_path) if trajectory_output_path else None,
        "output_video": str(output_path) if output_path else None,
    }


def _track_id_to_color(track_id: int) -> tuple[int, int, int]:
    """根据 track ID 生成稳定的 BGR 颜色。"""
    track_id = int(track_id)
    np.random.seed(track_id % 256)
    color = tuple(int(c) for c in np.random.randint(50, 255, size=3))
    return color


def draw_trajectory_on_image(
    image: np.ndarray,
    trajectory: dict[int, list[dict]],
    line_width: int = 2,
) -> np.ndarray:
    """在单张图片上绘制所有目标的运动轨迹。"""
    annotated = image.copy()
    for track_id, points in trajectory.items():
        color = _track_id_to_color(track_id)
        pts = [tuple(p["center"]) for p in points]
        if len(pts) >= 2:
            pts_array = np.array(pts, dtype=np.int32)
            cv2.polylines(annotated, [pts_array], False, color, line_width)
        if pts:
            cv2.circle(annotated, pts[-1], 5, color, -1)
            cv2.putText(
                annotated,
                f"ID{track_id}",
                (pts[-1][0] + 8, pts[-1][1] - 8),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                1,
                cv2.LINE_AA,
            )
    return annotated


if __name__ == "__main__":
    args = parse_args()
    result = track_video(
        video_path=args.video,
        model_path=args.model,
        tracker_type=args.tracker,
        confidence_threshold=args.conf,
        output_path=args.output,
        trajectory_output_path=args.trajectory_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
