import cv2
import os
import numpy as np

class VideoProcessor:
    def __init__(self):
        pass
    
    def sample_video(self, video_path, interval=2):
        frames = []
        timestamps = []
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if fps == 0:
            fps = 30
        
        sample_interval_frames = int(fps * interval)
        
        for i in range(0, frame_count, sample_interval_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if ret:
                frames.append(frame)
                timestamps.append(i / fps)
        
        cap.release()
        return frames, timestamps
    
    def save_frame(self, frame, output_path):
        cv2.imwrite(output_path, frame)
    
    def calculate_scene_change(self, frame1, frame2):
        gray1 = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(gray1, gray2)
        mean_diff = np.mean(diff)
        
        normalized_score = min(mean_diff / 50.0, 1.0)
        return normalized_score
    
    def calculate_motion_intensity(self, frame_sequence):
        if len(frame_sequence) < 2:
            return 0.0
        
        total_motion = 0.0
        for i in range(len(frame_sequence) - 1):
            gray1 = cv2.cvtColor(frame_sequence[i], cv2.COLOR_BGR2GRAY)
            gray2 = cv2.cvtColor(frame_sequence[i+1], cv2.COLOR_BGR2GRAY)
            
            flow = cv2.calcOpticalFlowFarneback(
                gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            
            magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
            total_motion += np.mean(magnitude)
        
        avg_motion = total_motion / (len(frame_sequence) - 1)
        normalized_score = min(avg_motion / 10.0, 1.0)
        return normalized_score
    
    def _create_test_frame(self, value):
        return np.ones((480, 640, 3), dtype=np.uint8) * value