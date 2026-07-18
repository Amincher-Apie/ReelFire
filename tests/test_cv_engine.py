import unittest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cv_engine.video_processor import VideoProcessor
from cv_engine.yolo_detector import YoloDetector
from cv_engine.highlight_scorer import HighlightScorer

class TestVideoProcessor(unittest.TestCase):
    def test_calculate_scene_change(self):
        processor = VideoProcessor()
        
        frame1 = processor._create_test_frame(0)
        frame2 = processor._create_test_frame(100)
        
        score = processor.calculate_scene_change(frame1, frame2)
        self.assertTrue(0 <= score <= 1)
    
    def test_calculate_motion_intensity(self):
        processor = VideoProcessor()
        
        frame1 = processor._create_test_frame(0)
        frame2 = processor._create_test_frame(50)
        
        sequence = [frame1, frame2]
        score = processor.calculate_motion_intensity(sequence)
        self.assertTrue(0 <= score <= 1)

class TestYoloDetector(unittest.TestCase):
    def test_detect_frames(self):
        detector = YoloDetector()
        
        import cv2
        test_frame = cv2.imread('tests/test_image.jpg')
        
        if test_frame is not None:
            results = detector.detect(test_frame)
            self.assertIsInstance(results, list)

class TestHighlightScorer(unittest.TestCase):
    def test_calculate_object_score(self):
        scorer = HighlightScorer()
        
        detections = [{'class': 'person', 'confidence': 0.9}] * 5
        score = scorer.calculate_object_score(detections)
        self.assertTrue(0 <= score <= 1)
    
    def test_calculate_highlight_score(self):
        scorer = HighlightScorer()
        
        score = scorer.calculate_highlight_score(0.8, 0.6, 0.4)
        expected = 0.8 * 0.45 + 0.6 * 0.35 + 0.4 * 0.20
        self.assertAlmostEqual(score, expected, places=4)
    
    def test_select_segments(self):
        scorer = HighlightScorer()
        
        keyframes = [
            {'timestamp': 10.0, 'highlight_score': 0.9},
            {'timestamp': 20.0, 'highlight_score': 0.8},
            {'timestamp': 30.0, 'highlight_score': 0.7},
        ]
        
        segments = scorer._select_segments(keyframes, 60.0, target_duration=30.0)
        self.assertGreaterEqual(len(segments), 1)
        
        for seg in segments:
            self.assertGreaterEqual(seg['end'], seg['start'])
            self.assertGreaterEqual(seg['start'], 0)
            self.assertLessEqual(seg['end'], 60.0)

if __name__ == '__main__':
    unittest.main()