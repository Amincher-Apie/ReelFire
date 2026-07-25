"""自定义 YOLO 模型训练脚本。

用法:
    python -m cv_engine.train                          # 使用默认配置训练
    python -m cv_engine.train --data data/custom.yaml  # 指定数据集配置
    python -m cv_engine.train --epochs 50 --imgsz 640  # 自定义超参数
    python -m cv_engine.train --resume                 # 从上次中断处继续训练
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ultralytics import YOLO


DEFAULT_DATA = Path(__file__).resolve().parent.parent / "data" / "custom.yaml"
DEFAULT_PRETRAINED = Path(__file__).resolve().parent.parent / "models" / "yolo11n.pt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自定义 YOLO 模型训练")
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA,
        help="YOLO 数据集配置文件路径 (default: data/custom.yaml)",
    )
    parser.add_argument(
        "--pretrained",
        type=Path,
        default=DEFAULT_PRETRAINED,
        help="预训练权重路径 (default: models/yolo11n.pt)",
    )
    parser.add_argument("--epochs", type=int, default=100, help="训练轮数 (default: 100)")
    parser.add_argument("--imgsz", type=int, default=640, help="输入图片尺寸 (default: 640)")
    parser.add_argument("--batch", type=int, default=16, help="batch size (default: 16)")
    parser.add_argument("--device", type=str, default="0", help="训练设备: 0/cpu/mps (default: 0)")
    parser.add_argument("--workers", type=int, default=4, help="数据加载线程数 (default: 4)")
    parser.add_argument("--lr0", type=float, default=0.01, help="初始学习率 (default: 0.01)")
    parser.add_argument("--lrf", type=float, default=0.01, help="最终学习率系数 (default: 0.01)")
    parser.add_argument("--patience", type=int, default=20, help="早停耐心值 (default: 20)")
    parser.add_argument("--project", type=Path, default=None, help="训练输出目录")
    parser.add_argument("--name", type=str, default="custom_fps", help="训练实验名称")
    parser.add_argument("--resume", action="store_true", help="从上次中断处继续训练")
    parser.add_argument("--save-period", type=int, default=10, help="每 N 轮保存一次权重 (default: 10)")
    return parser.parse_args()


def run(args: argparse.Namespace) -> Path:
    data_path = Path(args.data).resolve()
    if not data_path.is_file():
        raise FileNotFoundError(
            f"数据集配置文件不存在: {data_path}\n"
            "请先创建 data/custom.yaml，参考 data/custom.yaml.example"
        )

    pretrained = Path(args.pretrained).resolve()
    if not pretrained.is_file():
        raise FileNotFoundError(
            f"预训练权重不存在: {pretrained}\n"
            "运行 python setup_environment.py 下载 yolo11n.pt"
        )

    model = YOLO(str(pretrained))

    results = model.train(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        lr0=args.lr0,
        lrf=args.lrf,
        patience=args.patience,
        project=str(args.project) if args.project else None,
        name=args.name,
        resume=args.resume,
        save_period=args.save_period,
        plots=True,
        exist_ok=True,
        verbose=True,
    )

    print(f"\n训练完成，最佳权重位于: {results.save_dir / 'weights' / 'best.pt'}")
    return results.save_dir


if __name__ == "__main__":
    run(parse_args())
