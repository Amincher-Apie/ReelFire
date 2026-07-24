"""数据集准备辅助脚本。

将 LabelNazuki 导出的 YOLO TXT 标注文件整理为标准 YOLO 训练目录结构:

    data/custom_dataset/
    ├── images/
    │   ├── train/
    │   └── val/
    └── labels/
        ├── train/
        └── val/

用法:
    # 图片和标注在同一目录
    python -m data.prepare_dataset --source path/to/labeled_images --output data/custom_dataset

    # 图片和标注在不同目录（如 LabelNazuki 导出到子目录）
    python -m data.prepare_dataset --source img --labels img/img_label --output data/custom_dataset
"""

from __future__ import annotations

import argparse
import random
import shutil
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="准备 YOLO 训练数据集")
    parser.add_argument("--source", type=Path, required=True, help="图片所在目录")
    parser.add_argument("--labels", type=Path, default=None,
                        help="标注文件所在目录（默认与图片同目录）")
    parser.add_argument("--output", type=Path, default=Path("data/custom_dataset"),
                        help="输出数据集根目录 (default: data/custom_dataset)")
    parser.add_argument("--val-ratio", type=float, default=0.2,
                        help="验证集比例 (default: 0.2)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (default: 42)")
    return parser.parse_args()


def prepare(source: Path, labels: Path, output: Path,
            val_ratio: float = 0.2, seed: int = 42) -> None:
    source = source.resolve()
    labels = labels.resolve() if labels else source
    output = output.resolve()

    images_dir = output / "images"
    labels_dir = output / "labels"
    train_img = images_dir / "train"
    val_img = images_dir / "val"
    train_lbl = labels_dir / "train"
    val_lbl = labels_dir / "val"

    for d in [train_img, val_img, train_lbl, val_lbl]:
        d.mkdir(parents=True, exist_ok=True)

    supported_ext = {".jpg", ".jpeg", ".png", ".bmp"}
    image_files = [f for f in source.iterdir() if f.suffix.lower() in supported_ext]

    if not image_files:
        raise FileNotFoundError(f"在 {source} 中未找到图片文件")

    random.seed(seed)
    random.shuffle(image_files)

    val_count = max(1, int(len(image_files) * val_ratio))
    val_files = image_files[:val_count]
    train_files = image_files[val_count:]

    print(f"图片目录: {source}")
    print(f"标注目录: {labels}")
    print(f"总计 {len(image_files)} 张图片")
    print(f"  训练集: {len(train_files)} 张")
    print(f"  验证集: {len(val_files)} 张")
    print()

    missing = 0
    for img_file in train_files:
        if not _copy_pair(img_file, labels, train_img, train_lbl):
            missing += 1
    for img_file in val_files:
        if not _copy_pair(img_file, labels, val_img, val_lbl):
            missing += 1

    if missing > 0:
        print(f"\n⚠️  有 {missing} 张图片未找到对应标注文件")

    print(f"\n数据集已保存到: {output}")


def _copy_pair(img_file: Path, labels_dir: Path,
               dest_img: Path, dest_lbl: Path) -> bool:
    """复制图片和对应的标注文件，返回是否找到标注文件"""
    shutil.copy2(img_file, dest_img / img_file.name)
    label_file = labels_dir / (img_file.stem + ".txt")
    if label_file.is_file():
        shutil.copy2(label_file, dest_lbl / label_file.name)
        return True
    print(f"  警告: 未找到标注文件 {img_file.stem}.txt，跳过标注")
    return False


if __name__ == "__main__":
    args = parse_args()
    prepare(args.source, args.labels, args.output, args.val_ratio, args.seed)
