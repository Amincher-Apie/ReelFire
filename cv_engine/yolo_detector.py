from ultralytics import YOLO
import os

class YoloDetector:
    def __init__(self, model_path='models/yolo11n.pt'):
        self.model_path = model_path
        self.model = None
        self._load_model()
    
    def _load_model(self):
        if not os.path.exists(self.model_path):
            raise FileNotFoundError(
                f"Model file not found at {self.model_path}\n"
                "Please manually download yolo11n.pt from:\n"
                "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo11n.pt\n"
                "and place it in the models/ directory."
            )
        
        self.model = YOLO(self.model_path)
    
    def detect(self, frame):
        results = self.model(frame)
        detections = []
        
        for result in results:
            if result.boxes is not None:
                for box in result.boxes:
                    x1, y1, x2, y2 = [float(v) for v in box.xyxy[0].tolist()]
                    confidence = float(box.conf[0])
                    class_id = int(box.cls[0])
                    class_name = self.model.names[class_id]
                    
                    detections.append({
                        'class': class_name,
                        'confidence': confidence,
                        'bbox': [x1, y1, x2, y2],
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