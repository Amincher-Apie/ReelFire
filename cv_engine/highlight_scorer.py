import cv2
import os
import numpy as np
import json

class HighlightScorer:
    def __init__(self):
        self.object_weight = 0.45
        self.scene_change_weight = 0.35
        self.motion_weight = 0.20
    
    def calculate_object_score(self, detections, max_objects=20):
        count = len(detections)
        score = min(count / max_objects, 1.0)
        return score
    
    def calculate_scene_change_score(self, frame, prev_frame):
        if prev_frame is None:
            return 0.0
        
        gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        diff = cv2.absdiff(gray1, gray2)
        mean_diff = float(np.mean(diff))
        
        score = float(min(mean_diff / 50.0, 1.0))
        return score
    
    def calculate_motion_score(self, frame, prev_frame):
        if prev_frame is None:
            return 0.0
        
        gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        
        try:
            flow = cv2.calcOpticalFlowFarneback(
                gray1, gray2, None, 0.5, 3, 15, 3, 5, 1.2, 0
            )
            magnitude = np.sqrt(flow[..., 0]**2 + flow[..., 1]**2)
            mean_magnitude = float(np.mean(magnitude))
            score = float(min(mean_magnitude / 10.0, 1.0))
        except:
            score = 0.0
        
        return score
    
    def calculate_highlight_score(self, object_score, scene_change_score, motion_score):
        return (
            object_score * self.object_weight +
            scene_change_score * self.scene_change_weight +
            motion_score * self.motion_weight
        )
    
    def analyze(self, frames, detections_list, timestamps, job_id):
        keyframes = []
        prev_frame = None
        
        for i, (frame, detections, timestamp) in enumerate(zip(frames, detections_list, timestamps)):
            object_score = self.calculate_object_score(detections)
            scene_change_score = self.calculate_scene_change_score(frame, prev_frame)
            motion_score = self.calculate_motion_score(frame, prev_frame)
            highlight_score = self.calculate_highlight_score(object_score, scene_change_score, motion_score)
            
            keyframe_entry = {
                'frame_index': i,
                'timestamp': round(timestamp, 2),
                'object_score': round(object_score, 4),
                'scene_change_score': round(scene_change_score, 4),
                'motion_score': round(motion_score, 4),
                'highlight_score': round(highlight_score, 4),
                'objects': [{
                    'class': d['class'],
                    'confidence': round(d['confidence'], 4),
                    'bbox': [round(x, 2) for x in d['bbox']]
                } for d in detections]
            }
            
            keyframes.append(keyframe_entry)
            prev_frame = frame
        
        sorted_keyframes = sorted(keyframes, key=lambda x: x['highlight_score'], reverse=True)
        
        selected_segments = self._select_segments(sorted_keyframes, timestamps[-1] if timestamps else 60.0)
        
        result = {
            'job_id': job_id,
            'total_frames': len(frames),
            'sample_interval': 2,
            'keyframes': keyframes,
            'top_keyframes': sorted_keyframes[:10],
            'recommended_segments': selected_segments,
            'scoring_weights': {
                'object_weight': self.object_weight,
                'scene_change_weight': self.scene_change_weight,
                'motion_weight': self.motion_weight
            }
        }
        
        return result
    
    def _select_segments(self, sorted_keyframes, video_duration, target_duration=30.0, min_segment_length=5.0):
        segments = []
        used_time_ranges = []
        
        for keyframe in sorted_keyframes:
            timestamp = keyframe['timestamp']
            segment_start = max(0, timestamp - min_segment_length / 2)
            segment_end = min(video_duration, timestamp + min_segment_length / 2)
            
            overlap = False
            for (used_start, used_end) in used_time_ranges:
                if not (segment_end <= used_start or segment_start >= used_end):
                    overlap = True
                    break
            
            if not overlap:
                segments.append({
                    'start': round(segment_start, 2),
                    'end': round(segment_end, 2),
                    'score': keyframe['highlight_score'],
                    'center_timestamp': round(timestamp, 2)
                })
                used_time_ranges.append((segment_start, segment_end))
            
            total_selected = sum(s['end'] - s['start'] for s in segments)
            if total_selected >= target_duration:
                break
        
        segments.sort(key=lambda x: x['start'])
        
        return segments