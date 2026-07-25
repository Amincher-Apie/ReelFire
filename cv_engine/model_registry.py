"""Model registry for switching between official and custom YOLO models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ModelInfo:
    """Information about a registered YOLO model."""

    model_id: str
    display_name: str
    model_path: Path
    description: str = ""
    class_names: list[str] = field(default_factory=list)
    num_classes: int = 0
    is_custom: bool = False
    mAP50: float = 0.0
    mAP50_95: float = 0.0


class ModelRegistry:
    """Registry for managing available YOLO models."""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self._models: dict[str, ModelInfo] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register built-in models."""
        # Official YOLO model
        official_path = self.base_dir / "models" / "yolo11n.pt"
        if official_path.exists():
            self.register(
                ModelInfo(
                    model_id="official",
                    display_name="YOLO11n (Official)",
                    model_path=official_path,
                    description="Official YOLO11n pretrained on COCO (80 classes)",
                    num_classes=80,
                    is_custom=False,
                )
            )

        # Custom FPS model (v3)
        custom_v3_path = (
            self.base_dir / "runs" / "detect" / "custom_fps_v3" / "weights" / "best.pt"
        )
        if custom_v3_path.exists():
            self.register(
                ModelInfo(
                    model_id="custom_v3",
                    display_name="Custom FPS v3",
                    model_path=custom_v3_path,
                    description="Custom YOLO trained on CS2 FPS data (4 classes: CT/T/Rifle/Pistol)",
                    class_names=[
                        "character_ct",
                        "character_t",
                        "weapon_rifle",
                        "weapon_pistol",
                    ],
                    num_classes=4,
                    is_custom=True,
                    mAP50=0.791,
                    mAP50_95=0.502,
                )
            )

        # Custom FPS model (v5)
        custom_v5_path = (
            self.base_dir / "runs" / "detect" / "custom_fps_v5" / "weights" / "best.pt"
        )
        if custom_v5_path.exists():
            self.register(
                ModelInfo(
                    model_id="custom_v5",
                    display_name="Custom FPS v5 (CS2)",
                    model_path=custom_v5_path,
                    description="Custom YOLO v5 trained on CS2 FPS data with data augmentation (4 classes)",
                    class_names=[
                        "character_ct",
                        "character_t",
                        "weapon_rifle",
                        "weapon_pistol",
                    ],
                    num_classes=4,
                    is_custom=True,
                    mAP50=0.783,
                    mAP50_95=0.584,
                )
            )

        # Valorant model (v1)
        valorant_v1_path = (
            self.base_dir / "runs" / "detect" / "valorant_v1" / "weights" / "best.pt"
        )
        if valorant_v1_path.exists():
            self.register(
                ModelInfo(
                    model_id="valorant_v1",
                    display_name="Valorant v1",
                    model_path=valorant_v1_path,
                    description="Custom YOLO trained on Valorant data (2 classes: enemy/weapon)",
                    class_names=["enemy", "weapon"],
                    num_classes=2,
                    is_custom=True,
                    mAP50=0.796,
                    mAP50_95=0.582,
                )
            )

        # Valorant model (v2)
        valorant_v2_path = (
            self.base_dir / "runs" / "detect" / "valorant_v2" / "weights" / "best.pt"
        )
        if valorant_v2_path.exists():
            self.register(
                ModelInfo(
                    model_id="valorant_v2",
                    display_name="Valorant v2",
                    model_path=valorant_v2_path,
                    description="Custom YOLO v2 trained on Valorant data with more samples (2 classes: enemy/weapon)",
                    class_names=["enemy", "weapon"],
                    num_classes=2,
                    is_custom=True,
                    mAP50=0.796,
                    mAP50_95=0.617,
                )
            )

    def register(self, model_info: ModelInfo) -> None:
        """Register a model."""
        self._models[model_info.model_id] = model_info

    def get(self, model_id: str) -> Optional[ModelInfo]:
        """Get model info by ID."""
        return self._models.get(model_id)

    def get_default(self) -> ModelInfo:
        """Get the default model (prefer custom v5, then custom v3, then official)."""
        for model_id in ["custom_v5", "custom_v3", "official"]:
            if model_id in self._models:
                return self._models[model_id]
        raise RuntimeError("No models available in registry")

    def list_models(self) -> list[ModelInfo]:
        """List all registered models."""
        return list(self._models.values())

    def resolve_model_path(self, model_id: Optional[str] = None) -> Path:
        """Resolve model path from model ID. Returns default if model_id is None."""
        if model_id:
            model = self.get(model_id)
            if model is None:
                raise ValueError(
                    f"Unknown model: {model_id}. Available: {list(self._models.keys())}"
                )
            return model.model_path
        return self.get_default().model_path
