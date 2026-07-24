"""图片检测支持模块，扩展原有仅支持视频的推理流程。

用法:
    python -m cv_engine.image_detector --image path/to/image.jpg --model models/custom.pt
    python -m cv_engine.image_detector --image path/to/image.jpg --output outputs/detection.jpg
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from cv_engine.yolo_detector import YoloDetector


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="图片目标检测")
    parser.add_argument("--image", type=Path, required=True, help="输入图片路径")
    parser.add_argument("--model", type=Path, default=Path("models/yolo11n.pt"), help="YOLO 模型权重")
    parser.add_argument("--output", type=Path, default=None, help="带检测框的输出图片路径")
    parser.add_argument("--json-output", type=Path, default=None, help="检测结果 JSON 输出路径")
    parser.add_argument("--conf", type=float, default=0.35, help="置信度阈值 (default: 0.35)")
    return parser.parse_args()


def detect_image(
    image_path: Path,
    model_path: Path,
    confidence_threshold: float = 0.35,
    output_path: Path | None = None,
    json_output_path: Path | None = None,
) -> dict:
    """对单张图片进行 YOLO 检测，返回结构化结果。"""
    if not image_path.is_file():
        raise FileNotFoundError(f"图片不存在: {image_path}")

    detector = YoloDetector(str(model_path), confidence_threshold)

    frame = cv2.imread(str(image_path))
    if frame is None:
        raise ValueError(f"无法读取图片: {image_path}")

    detections = detector.detect(frame)

    result = {
        "image": str(image_path),
        "model": model_path.name,
        "image_size": {
            "width": int(frame.shape[1]),
            "height": int(frame.shape[0]),
        },
        "detection_count": len(detections),
        "detections": detections,
        "class_summary": _summarize_classes(detections),
    }

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        annotated = _draw_detections(frame, detections)
        cv2.imwrite(str(output_path), annotated)
        result["annotated_image"] = str(output_path)

    if json_output_path:
        json_output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(json_output_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def _summarize_classes(detections: list[dict]) -> dict:
    """按类别汇总检测数量。"""
    summary: dict[str, int] = {}
    for d in detections:
        cls_name = d["class"]
        summary[cls_name] = summary.get(cls_name, 0) + 1
    return summary


def _draw_detections(frame, detections: list[dict]):
    """在图片上绘制检测框。"""
    annotated = frame.copy()
    for d in detections:
        x1, y1, x2, y2 = [int(v) for v in d["bbox"]]
        conf = d["confidence"]
        cls_name = d["class"]
        label = f"{cls_name} {conf:.2f}"

        cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 80), 2)
        (text_width, text_height), _ = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1
        )
        text_top = max(0, y1 - text_height - 8)
        cv2.rectangle(
            annotated,
            (x1, text_top),
            (min(annotated.shape[1] - 1, x1 + text_width + 8), y1),
            (0, 255, 80),
            -1,
        )
        cv2.putText(
            annotated,
            label,
            (x1 + 4, max(text_height + 1, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (10, 20, 10),
            1,
            cv2.LINE_AA,
        )
    return annotated


if __name__ == "__main__":
    args = parse_args()
    result = detect_image(
        image_path=args.image,
        model_path=args.model,
        confidence_threshold=args.conf,
        output_path=args.output,
        json_output_path=args.json_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
