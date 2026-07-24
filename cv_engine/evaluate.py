"""多模型对比评估模块。

用法:
    python -m cv_engine.evaluate --models models/yolo11n.pt models/custom.pt --data data/custom.yaml
    python -m cv_engine.evaluate --models models/yolo11n.pt models/custom.pt --data data/custom.yaml --output outputs/eval_comparison.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ultralytics import YOLO


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="多模型对比评估 (P/R/mAP)")
    parser.add_argument(
        "--models",
        type=Path,
        nargs="+",
        required=True,
        help="待对比的模型权重路径（至少 2 个）",
    )
    parser.add_argument("--data", type=Path, required=True, help="验证集 data.yaml 路径")
    parser.add_argument("--imgsz", type=int, default=640, help="输入图片尺寸 (default: 640)")
    parser.add_argument("--batch", type=int, default=16, help="batch size (default: 16)")
    parser.add_argument("--device", type=str, default="0", help="设备: 0/cpu/mps")
    parser.add_argument("--conf", type=float, default=0.001, help="置信度阈值 (default: 0.001)")
    parser.add_argument("--iou", type=float, default=0.65, help="IoU 阈值 (default: 0.65)")
    parser.add_argument("--output", type=Path, default=None, help="评估结果 JSON 输出路径")
    return parser.parse_args()


def evaluate_model(
    model_path: Path,
    data_path: Path,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "0",
    conf: float = 0.001,
    iou: float = 0.65,
) -> dict:
    """评估单个模型，返回指标字典。"""
    model = YOLO(str(model_path.resolve()))
    results = model.val(
        data=str(data_path.resolve()),
        imgsz=imgsz,
        batch=batch,
        device=device,
        conf=conf,
        iou=iou,
        verbose=False,
        plots=True,
    )

    return {
        "model": model_path.name,
        "metrics": {
            "mAP50": round(float(results.box.map50), 4),
            "mAP50-95": round(float(results.box.map), 4),
            "precision": round(float(results.box.mp), 4),
            "recall": round(float(results.box.mr), 4),
        },
        "per_class": {
            str(name): {
                "mAP50": round(float(metrics[2]), 4),
                "mAP50-95": round(float(metrics[3]), 4),
                "precision": round(float(metrics[0]), 4),
                "recall": round(float(metrics[1]), 4),
            }
            for name, metrics in results.box.results_dict.items()
            if isinstance(metrics, (list, tuple)) and len(metrics) >= 4
        } if hasattr(results.box, "results_dict") else {},
    }


def compare_models(
    model_paths: list[Path],
    data_path: Path,
    imgsz: int = 640,
    batch: int = 16,
    device: str = "0",
    conf: float = 0.001,
    iou: float = 0.65,
) -> dict:
    """对比多个模型，返回对比结果。"""
    if len(model_paths) < 2:
        raise ValueError("至少需要 2 个模型进行对比")

    results = []
    for model_path in model_paths:
        print(f"评估模型: {model_path.name} ...")
        result = evaluate_model(
            model_path, data_path, imgsz, batch, device, conf, iou
        )
        results.append(result)
        print(f"  mAP50={result['metrics']['mAP50']}, mAP50-95={result['metrics']['mAP50-95']}")

    return {
        "data": str(data_path),
        "imgsz": imgsz,
        "conf": conf,
        "iou": iou,
        "models": results,
        "comparison": _build_comparison_table(results),
    }


def _build_comparison_table(results: list[dict]) -> dict:
    """构建对比表格数据。"""
    metrics = ["mAP50", "mAP50-95", "precision", "recall"]
    table = {}
    for metric in metrics:
        table[metric] = {
            r["model"]: r["metrics"][metric] for r in results
        }
    return table


if __name__ == "__main__":
    args = parse_args()
    result = compare_models(
        model_paths=[Path(p) for p in args.models],
        data_path=args.data,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        conf=args.conf,
        iou=args.iou,
    )

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n对比结果已保存到: {args.output}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
