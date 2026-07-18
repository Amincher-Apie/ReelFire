import cv2
import os
import numpy as np

class VideoProcessor:
    def __init__(self):
        pass
    
    def sample_video(self, video_path, interval=1):
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
    
    def has_audio_track(self, video_path):
        try:
            import subprocess
            import json
            
            ffmpeg_path = self._find_ffmpeg()
            if not ffmpeg_path:
                return False
            
            cmd = [ffmpeg_path, '-i', video_path, '-hide_banner', '-print_format', 'json', '-show_streams', '-loglevel', 'error']
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode != 0:
                return False
            
            try:
                info = json.loads(result.stdout)
                streams = info.get('streams', [])
                for stream in streams:
                    if stream.get('codec_type') == 'audio':
                        return True
                return False
            except json.JSONDecodeError:
                return False
        except Exception:
            return False
    
    def get_video_info(self, video_path):
        info = {
            'has_audio': False,
            'duration': 0.0,
            'fps': 30.0,
            'width': 0,
            'height': 0
        }
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return info
        
        info['fps'] = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        info['duration'] = frame_count / info['fps'] if info['fps'] > 0 else 0.0
        info['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        info['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        cap.release()
        
        info['has_audio'] = self.has_audio_track(video_path)
        
        return info
    
    def _find_ffmpeg(self):
        import shutil
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path
        
        common_paths = [
            r'D:\Ffmpeg\ffmpeg-8.1.2-full_build\bin\ffmpeg.exe',
            r'C:\ffmpeg\bin\ffmpeg.exe',
            r'C:\Program Files\ffmpeg\bin\ffmpeg.exe',
            r'D:\ffmpeg\bin\ffmpeg.exe',
        ]
        for path in common_paths:
            if os.path.exists(path):
                return path
        
        return None
    
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