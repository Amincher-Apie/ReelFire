"""绘制多模型评估对比图。

用法:
    python -m cv_engine.plot_eval --cs2 outputs/eval_cs2_comparison.json --valorant outputs/eval_valorant_comparison.json --output outputs/eval_comparison.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# 设置中文字体（Windows）
plt.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def load_comparison(path: Path, label_prefix: str) -> list[dict]:
    """加载评估 JSON，返回带标签的模型指标列表。"""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    models = data.get("models", [])
    # 按顺序赋予标签（第一个=v3/v1，第二个=v5/v2）
    suffixes = ["v3", "v5"] if "cs2" in label_prefix.lower() else ["v1", "v2"]
    result = []
    for i, model in enumerate(models):
        suffix = suffixes[i] if i < len(suffixes) else f"m{i}"
        result.append({
            "label": f"{label_prefix} {suffix}",
            "metrics": model["metrics"],
        })
    return result


def plot_comparison(cs2_models: list[dict], valorant_models: list[dict], output: Path) -> None:
    """绘制 4 个指标的对比柱状图。"""
    all_models = cs2_models + valorant_models
    labels = [m["label"] for m in all_models]
    metrics_keys = ["precision", "recall", "mAP50", "mAP50-95"]
    titles = ["Precision", "Recall", "mAP50", "mAP50-95"]

    # 颜色：CS2 用蓝色系，Valorant 用橙色系
    colors = ["#4C72B0", "#55A868", "#DD8452", "#C44E52"]

    fig, axes = plt.subplots(1, 4, figsize=(16, 5))
    x = np.arange(len(labels))

    for ax, key, title in zip(axes, metrics_keys, titles):
        values = [m["metrics"][key] for m in all_models]
        bars = ax.bar(x, values, color=colors, edgecolor="black", linewidth=0.8)
        ax.set_title(title, fontsize=13, fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9)
        ax.set_ylim(0, 1.05)
        ax.grid(axis="y", linestyle="--", alpha=0.4)
        # 在柱子上方显示数值
        for bar, value in zip(bars, values):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.02,
                f"{value:.3f}",
                ha="center",
                va="bottom",
                fontsize=9,
            )

    fig.suptitle("多模型评估对比 (CS2 v3/v5 + Valorant v1/v2)", fontsize=15, fontweight="bold")
    plt.tight_layout(rect=[0, 0, 1, 0.95])
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(str(output), dpi=150, bbox_inches="tight")
    plt.close()
    print(f"对比图已保存到: {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="绘制多模型评估对比图")
    parser.add_argument("--cs2", type=Path, required=True, help="CS2 评估 JSON 路径")
    parser.add_argument("--valorant", type=Path, required=True, help="Valorant 评估 JSON 路径")
    parser.add_argument("--output", type=Path, default=Path("outputs/eval_comparison.png"), help="输出图片路径")
    args = parser.parse_args()

    cs2_models = load_comparison(args.cs2, "CS2")
    valorant_models = load_comparison(args.valorant, "Valorant")
    plot_comparison(cs2_models, valorant_models, args.output)


if __name__ == "__main__":
    main()
