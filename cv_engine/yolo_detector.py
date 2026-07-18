from ultralytics import YOLO
from pathlib import Path

class YoloDetector:
    def __init__(self, model_path='models/yolo11n.pt', confidence_threshold=0.35):
        self.model_path = Path(model_path)
        self.confidence_threshold = float(confidence_threshold)
        self.model = None
        self._load_model()

    def _load_model(self):
        if not self.model_path.is_file():
            raise FileNotFoundError(
                f"Model file not found at {self.model_path}\n"
                "Please manually download yolo11n.pt from:\n"
                "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt\n"
                "and place it in the models/ directory."
            )

        self.model = YOLO(str(self.model_path))

    def detect(self, frame):
        results = self.model.predict(
            source=frame,
            conf=self.confidence_threshold,
            verbose=False,
        )
        detections = []

        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = str(self.model.names[class_id])

                    detections.append({
                        'class': class_name,
                        'confidence': confidence,
                        'bbox': [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                        'class_id': class_id
                    })

        return detections

    def detect_frames(self, frames):
        all_results = []
        for frame in frames:
            detections = self.detect(frame)
            all_results.append(detections)
        return all_results

    def get_object_count(self, detections):
        return len(detections)

    def get_high_confidence_objects(self, detections, threshold=0.5):
        return [d for d in detections if d['confidence'] >= threshold]
