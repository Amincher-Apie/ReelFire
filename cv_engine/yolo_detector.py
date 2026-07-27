from ultralytics import YOLO
from pathlib import Path

class YoloDetector:
    def __init__(
        self,
        model_path='models/yolo11n.pt',
        confidence_threshold=0.35,
        batch_size=8,
        device=None,
        image_size=640,
    ):
        self.model_path = Path(model_path)
        self.confidence_threshold = float(confidence_threshold)
        self.batch_size = max(1, int(batch_size))
        self.device = device
        self.image_size = max(320, int(image_size))
        self.use_half = False
        self.model = None
        self._load_model()

    def _load_model(self):
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Model file not found at {self.model_path}\n"
                "Run `python setup_environment.py` to download and verify "
                "the official yolo11n.pt model."
            )

        self.model = YOLO(str(self.model_path))
        if self.device is None:
            try:
                import torch

                self.device = "0" if torch.cuda.is_available() else "cpu"
            except ImportError:
                self.device = "cpu"
        self.use_half = str(self.device).lower() != "cpu"

    def _predict_options(self):
        options = {
            "conf": self.confidence_threshold,
            "verbose": False,
            "imgsz": getattr(self, "image_size", 640),
        }
        device = getattr(self, "device", None)
        if device is not None:
            options["device"] = device
            options["half"] = bool(getattr(self, "use_half", False))
        return options

    def detect(self, frame):
        results = self.model.predict(
            source=frame,
            **self._predict_options(),
        )
        return self._parse_result(results[0]) if results else []

    def reset_tracking(self):
        predictor = getattr(self.model, "predictor", None)
        trackers = getattr(predictor, "trackers", None)
        if not trackers:
            return
        for tracker in trackers:
            reset = getattr(tracker, "reset", None)
            if callable(reset):
                reset()

    def track_frame(self, frame, tracker="bytetrack.yaml"):
        results = self.model.track(
            source=frame,
            tracker=tracker,
            persist=True,
            **self._predict_options(),
        )
        return (
            self._parse_result(results[0], include_track_id=True)
            if results
            else []
        )

    def associate_detections(
        self,
        detection_frames,
        tracker="bytetrack.yaml",
        sample_fps=2.0,
        track_buffer_seconds=2.0,
    ):
        """Run a fresh ByteTrack scope over existing YOLO detections."""
        import numpy as np

        from ultralytics.trackers.byte_tracker import BYTETracker
        from ultralytics.utils import YAML, IterableSimpleNamespace
        from ultralytics.utils.checks import check_yaml

        class DetectionSet:
            def __init__(self, rows):
                self.rows = np.asarray(rows, dtype=np.float32).reshape(-1, 6)

            @property
            def conf(self):
                return self.rows[:, 4]

            @property
            def cls(self):
                return self.rows[:, 5]

            @property
            def xywh(self):
                boxes = self.rows[:, :4]
                if not len(boxes):
                    return np.empty((0, 4), dtype=np.float32)
                result = boxes.copy()
                result[:, 0] = (boxes[:, 0] + boxes[:, 2]) / 2.0
                result[:, 1] = (boxes[:, 1] + boxes[:, 3]) / 2.0
                result[:, 2] = boxes[:, 2] - boxes[:, 0]
                result[:, 3] = boxes[:, 3] - boxes[:, 1]
                return result

            def __getitem__(self, index):
                return DetectionSet(self.rows[index])

            def __len__(self):
                return len(self.rows)

        config = IterableSimpleNamespace(**YAML.load(check_yaml(tracker)))
        if config.tracker_type != "bytetrack":
            raise ValueError(
                "Precomputed detection association currently requires ByteTrack"
            )
        config.track_buffer = max(
            2,
            round(
                max(0.1, float(track_buffer_seconds))
                * max(0.1, float(sample_fps))
            ),
        )
        byte_tracker = BYTETracker(config)
        associated_frames = []
        for detections in detection_frames:
            associated = []
            rows = []
            for detection in detections:
                copied = dict(detection)
                copied.pop("track_id", None)
                associated.append(copied)
                bbox = copied.get("bbox")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    rows.append([0.0, 0.0, 0.0, 0.0, 0.0, -1.0])
                    continue
                rows.append(
                    [
                        *[float(value) for value in bbox],
                        float(copied.get("confidence", 0.0)),
                        float(copied.get("class_id", -1)),
                    ]
                )
            tracked = byte_tracker.update(DetectionSet(rows))
            for row in tracked:
                detection_index = int(row[-1])
                if 0 <= detection_index < len(associated):
                    associated[detection_index]["track_id"] = int(row[-4])
            associated_frames.append(associated)
        return associated_frames

    def _parse_result(self, result, include_track_id=False):
        detections = []

        if result.boxes is not None:
            track_ids = (
                getattr(result.boxes, "id", None)
                if include_track_id
                else None
            )
            for index, box in enumerate(result.boxes):
                x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                confidence = float(box.conf[0])
                class_id = int(box.cls[0])
                class_name = str(self.model.names[class_id])

                detection = {
                    'class': class_name,
                    'confidence': confidence,
                    'bbox': [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                    'class_id': class_id
                }
                if track_ids is not None:
                    detection["track_id"] = int(track_ids[index].item())
                detections.append(detection)

        return detections

    def detect_frames(self, frames):
        all_results = []
        for start in range(0, len(frames), self.batch_size):
            batch = frames[start:start + self.batch_size]
            results = self.model.predict(
                source=batch,
                **self._predict_options(),
            )
            all_results.extend(self._parse_result(result) for result in results)
        return all_results

    def get_object_count(self, detections):
        return len(detections)

    def get_high_confidence_objects(self, detections, threshold=0.5):
        return [d for d in detections if d['confidence'] >= threshold]
