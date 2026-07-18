import cv2
import numpy as np

class HighlightScorer:
    def __init__(self):
        self.object_weight = 0.45
        self.scene_change_weight = 0.35
        self.motion_weight = 0.20
        self.kill_notification_weight = 0.0

    def calculate_object_score(self, detections, max_objects=5):
        count = len(detections)
        if count == 0:
            return 0.0
        score = min(count / max_objects, 1.0)
        return score

    def calculate_scene_change_score(self, frame, prev_frame):
        if prev_frame is None:
            return 0.0

        gray1 = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        diff = cv2.absdiff(gray1, gray2)
        mean_diff = float(np.mean(diff))

        score = float(min(mean_diff / 20.0, 1.0))
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
            score = float(min(mean_magnitude / 5.0, 1.0))
        except cv2.error:
            score = 0.0

        return score

    def calculate_kill_notification_score(self, frame):
        h, w = frame.shape[:2]

        roi_y_start = int(h * 0.55)
        roi_y_end = int(h * 0.75)
        roi_x_start = int(w * 0.25)
        roi_x_end = int(w * 0.75)

        roi = frame[roi_y_start:roi_y_end, roi_x_start:roi_x_end]
        roi_h, roi_w = roi.shape[:2]

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

        lower_red1 = np.array([0, 40, 60])
        upper_red1 = np.array([15, 255, 255])
        lower_red2 = np.array([160, 40, 60])
        upper_red2 = np.array([180, 255, 255])

        mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
        mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
        red_mask = mask1 | mask2

        red_pixels = np.sum(red_mask > 0)
        total_pixels = roi_h * roi_w
        red_ratio = red_pixels / total_pixels

        bgr_mean = np.mean(roi, axis=(0, 1))
        hsv_mean = np.mean(hsv, axis=(0, 1))

        if red_ratio < 0.005:
            print(f"[KILL SKIP] red_ratio={red_ratio:.4f} < 0.005, BGR mean={bgr_mean}, HSV mean={hsv_mean}")
            return 0.0

        contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        has_valid_rect = False
        best_contour_info = None
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 50:
                continue

            x, y, w_c, h_c = cv2.boundingRect(contour)
            aspect_ratio = w_c / float(h_c)

            if 1.0 < aspect_ratio < 8.0:
                has_valid_rect = True
                best_contour_info = f"area={area:.1f}, aspect={aspect_ratio:.2f}"
                break

        if not has_valid_rect:
            print(f"[KILL SKIP] No valid rectangle found, red_pixels={red_pixels}, contours={len(contours)}")
            return 0.0

        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        masked_gray = cv2.bitwise_and(gray, gray, mask=red_mask)

        _, white_mask = cv2.threshold(masked_gray, 160, 255, cv2.THRESH_BINARY)
        white_pixels = np.sum(white_mask > 0)

        if white_pixels < 15:
            print(f"[KILL SKIP] white_pixels={white_pixels} < 15")
            return 0.0

        text_ratio = white_pixels / red_pixels

        if text_ratio < 0.02:
            print(f"[KILL SKIP] text_ratio={text_ratio:.4f} < 0.02")
            return 0.0

        score = min(red_ratio * text_ratio * 100, 1.0)

        print(f"[KILL DETECTED] ROI: {roi_w}x{roi_h}, red_ratio={red_ratio:.4f}, white_pixels={white_pixels}, text_ratio={text_ratio:.4f}, score={score:.4f}, contour={best_contour_info}")

        return score

    def calculate_highlight_score(self, object_score, scene_change_score, motion_score, kill_notification_score=0.0):
        return (
            object_score * 0.45 +
            scene_change_score * 0.35 +
            motion_score * 0.20
        )

    def calculate_segment_tags(self, samples, segments):
        """Summarize real YOLO classes observed inside each candidate segment."""
        tag_stats = {}
        for segment in segments:
            segment_id = str(segment.get('id', 'segment'))
            start = float(segment.get('start', 0.0))
            end = float(segment.get('end', 0.0))
            for sample in samples:
                timestamp = float(sample.get('timestamp', -1.0))
                if not start <= timestamp <= end:
                    continue
                for detected in sample.get('objects', []):
                    class_name = str(detected.get('class', '')).strip()
                    if not class_name:
                        continue
                    entry = tag_stats.setdefault(
                        class_name,
                        {'count': 0, 'max_confidence': 0.0, 'segments': []},
                    )
                    entry['count'] += 1
                    confidence = float(detected.get('confidence', 0.0))
                    entry['max_confidence'] = max(entry['max_confidence'], confidence)
                    if segment_id not in entry['segments']:
                        entry['segments'].append(segment_id)

        ordered = sorted(tag_stats.items(), key=lambda item: (-item[1]['count'], item[0]))
        normalized = {
            class_name: {
                **details,
                'max_confidence': round(float(details['max_confidence']), 4),
            }
            for class_name, details in ordered
        }
        return {
            'total_tags': len(normalized),
            'tags': normalized,
            'summary': [f"{name}({details['count']})" for name, details in ordered],
        }

    def generate_cover_prompt(self, keyframe):
        """Generate an honest cover description from the selected real detections."""
        if not keyframe:
            return 'FPS 游戏精彩片段封面，突出高速对战画面与 ReelFire 标识'

        timestamp = float(keyframe.get('timestamp', 0.0))
        score = float(keyframe.get('highlight_score', 0.0))
        class_counts = {}
        for detected in keyframe.get('objects', []):
            class_name = str(detected.get('class', '')).strip()
            if class_name:
                class_counts[class_name] = class_counts.get(class_name, 0) + 1

        if not class_counts:
            return (
                f'FPS 游戏精彩片段封面，取自 {timestamp:.1f} 秒的高变化画面，'
                f'综合分数 {score:.3f}，不添加未检测到的目标'
            )

        objects = '、'.join(
            f'{class_name}×{count}'
            for class_name, count in sorted(
                class_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )[:3]
        )
        return (
            f'FPS 游戏精彩片段封面，取自 {timestamp:.1f} 秒，'
            f'突出真实检测目标 {objects}，综合分数 {score:.3f}，'
            '深色电竞风格，不虚构击杀或残局事件'
        )

    def analyze(self, frames, detections_list, timestamps, job_id):
        keyframes = []
        prev_frame = None

        for i, (frame, detections, timestamp) in enumerate(zip(frames, detections_list, timestamps)):
            object_score = self.calculate_object_score(detections)
            scene_change_score = self.calculate_scene_change_score(frame, prev_frame)
            motion_score = self.calculate_motion_score(frame, prev_frame)
            kill_notification_score = self.calculate_kill_notification_score(frame)
            highlight_score = self.calculate_highlight_score(object_score, scene_change_score, motion_score, kill_notification_score)

            keyframe_entry = {
                'frame_index': i,
                'timestamp': round(timestamp, 2),
                'object_score': round(object_score, 4),
                'scene_change_score': round(scene_change_score, 4),
                'motion_score': round(motion_score, 4),
                'kill_notification_score': round(kill_notification_score, 4),
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
                'motion_weight': self.motion_weight,
                'kill_notification_weight': self.kill_notification_weight
            }
        }

        return result

    def _select_segments(self, sorted_keyframes, video_duration, target_duration=60.0, min_segment_length=3.0):
        segments = []
        used_time_ranges = []
        shot_interval = 8.0

        if target_duration > video_duration:
            target_duration = video_duration

        if not sorted_keyframes:
            if video_duration >= min_segment_length:
                mid = video_duration / 2
                return [{
                    'start': round(max(0, mid - min_segment_length / 2), 2),
                    'end': round(min(video_duration, mid + min_segment_length / 2), 2),
                    'score': 0.5,
                    'center_timestamp': round(mid, 2)
                }]
            else:
                return [{
                    'start': 0.0,
                    'end': round(video_duration, 2),
                    'score': 0.5,
                    'center_timestamp': round(video_duration / 2, 2)
                }]

        selected_centers = []

        for keyframe in sorted_keyframes:
            timestamp = keyframe['timestamp']
            half_length = min_segment_length / 2

            if timestamp <= half_length:
                segment_start = 0.0
                segment_end = min(video_duration, half_length * 2)
            elif timestamp >= video_duration - half_length:
                segment_end = video_duration
                segment_start = max(0, video_duration - half_length * 2)
            else:
                segment_start = timestamp - half_length
                segment_end = timestamp + half_length

            segment_start = max(0.0, segment_start)
            segment_end = min(video_duration, segment_end)

            if segment_end <= segment_start:
                continue

            overlap = False
            for (used_start, used_end) in used_time_ranges:
                if not (segment_end <= used_start or segment_start >= used_end):
                    overlap = True
                    break

            same_shot = False
            for center in selected_centers:
                if abs(timestamp - center) < shot_interval:
                    same_shot = True
                    break

            if not overlap and not same_shot:
                segments.append({
                    'start': round(segment_start, 2),
                    'end': round(segment_end, 2),
                    'score': float(keyframe['highlight_score']),
                    'center_timestamp': round(timestamp, 2)
                })
                used_time_ranges.append((segment_start, segment_end))
                selected_centers.append(timestamp)

            total_selected = sum(s['end'] - s['start'] for s in segments)
            if total_selected >= target_duration:
                break

        if not segments:
            high_score_keyframes = [k for k in sorted_keyframes if k['highlight_score'] > 0.1]
            if high_score_keyframes:
                timestamp = high_score_keyframes[0]['timestamp']
                half_length = min_segment_length / 2
                segment_start = max(0.0, timestamp - half_length)
                segment_end = min(video_duration, timestamp + half_length)
                segments.append({
                    'start': round(segment_start, 2),
                    'end': round(segment_end, 2),
                    'score': float(high_score_keyframes[0]['highlight_score']),
                    'center_timestamp': round(timestamp, 2)
                })
            else:
                mid = video_duration / 2
                segments.append({
                    'start': round(max(0, mid - min_segment_length / 2), 2),
                    'end': round(min(video_duration, mid + min_segment_length / 2), 2),
                    'score': float(sorted_keyframes[0]['highlight_score']),
                    'center_timestamp': round(mid, 2)
                })

        if len(segments) == 1 and segments[0]['end'] - segments[0]['start'] < target_duration and video_duration > target_duration:
            current_end = segments[0]['end']
            if current_end < video_duration:
                remaining_duration = target_duration - (current_end - segments[0]['start'])
                new_end = min(video_duration, current_end + remaining_duration)
                segments[0]['end'] = round(new_end, 2)
                segments[0]['center_timestamp'] = (segments[0]['start'] + segments[0]['end']) / 2

        segments.sort(key=lambda x: x['start'])

        merged_segments = []
        for seg in segments:
            if not merged_segments:
                merged_segments.append(seg.copy())
            else:
                last = merged_segments[-1]
                if seg['start'] < last['end']:
                    last['end'] = max(last['end'], seg['end'])
                    if seg['score'] > last['score']:
                        last['score'] = seg['score']
                    last['center_timestamp'] = (last['start'] + last['end']) / 2
                else:
                    merged_segments.append(seg.copy())

        return merged_segments
