import cv2
import numpy as np
import json
import math
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

class VideoProcessor:
    def __init__(self):
        pass

    def sample_video(self, video_path, interval=1):
        """Compatibility helper that materializes all sampled frames."""

        frames = []
        timestamps = []
        for chunk in self.iter_sample_chunks(
            video_path,
            interval=interval,
            chunk_duration=float("inf"),
        ):
            frames.extend(chunk["frames"])
            timestamps.extend(chunk["timestamps"])
        return frames, timestamps

    def iter_sample_chunks(
        self,
        video_path,
        interval=1,
        chunk_duration=60,
        *,
        max_width=None,
    ):
        """Yield bounded chunks from one sequential decoder pass."""

        if interval <= 0:
            raise ValueError("Sample interval must be greater than zero")
        if chunk_duration <= 0:
            raise ValueError("Chunk duration must be greater than zero")

        video = self.get_video_info(video_path)
        duration = float(video.get("duration", 0.0))
        if duration <= 0:
            raise ValueError("Video duration is invalid")
        finite_chunk_duration = (
            duration if not math.isfinite(chunk_duration) else float(chunk_duration)
        )
        total_chunks = max(1, int(math.ceil(duration / finite_chunk_duration)))
        frames = []
        timestamps = []
        chunk_index = 0
        chunk_start = 0.0
        chunk_end = min(duration, finite_chunk_duration)

        for frame, timestamp in self.iter_samples(
            video_path,
            interval=interval,
            start=0.0,
            end=duration,
            max_width=max_width,
            video_info=video,
        ):
            while timestamp >= chunk_end and chunk_index < total_chunks - 1:
                yield {
                    "index": chunk_index,
                    "start": round(chunk_start, 3),
                    "end": round(chunk_end, 3),
                    "frames": frames,
                    "timestamps": timestamps,
                    "total_chunks": total_chunks,
                }
                chunk_index += 1
                chunk_start = chunk_index * finite_chunk_duration
                chunk_end = min(
                    duration,
                    (chunk_index + 1) * finite_chunk_duration,
                )
                frames = []
                timestamps = []
            frames.append(frame)
            timestamps.append(timestamp)

        yield {
            "index": chunk_index,
            "start": round(chunk_start, 3),
            "end": round(duration, 3),
            "frames": frames,
            "timestamps": timestamps,
            "total_chunks": total_chunks,
        }

    def iter_sample_windows(
        self,
        video_path,
        windows,
        *,
        interval=0.5,
        max_width=640,
        preserve_order=False,
    ):
        """Decode candidate windows with one seek per window."""

        ranges = [
            (float(window["start"]), float(window["end"]))
            for window in windows
        ]
        ordered = ranges if preserve_order else sorted(
            ranges,
            key=lambda value: value[0],
        )
        total = len(ordered)
        video = self.get_video_info(video_path)
        for index, (start, end) in enumerate(ordered):
            frames = []
            timestamps = []
            for frame, timestamp in self.iter_samples(
                video_path,
                interval=interval,
                start=start,
                end=end,
                max_width=max_width,
                video_info=video,
            ):
                frames.append(frame)
                timestamps.append(timestamp)
            yield {
                "index": index,
                "start": round(start, 3),
                "end": round(end, 3),
                "frames": frames,
                "timestamps": timestamps,
                "total_chunks": total,
            }

    def iter_samples(
        self,
        video_path,
        *,
        interval,
        start=0.0,
        end=None,
        max_width=None,
        video_info=None,
    ) -> Iterator[tuple[np.ndarray, float]]:
        if interval <= 0:
            raise ValueError("Sample interval must be greater than zero")
        video = (
            dict(video_info)
            if video_info is not None
            else self.get_video_info(video_path)
        )
        duration = float(video.get("duration", 0.0))
        stop = duration if end is None else min(float(end), duration)
        begin = min(max(float(start), 0.0), stop)
        if stop <= begin:
            return

        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path:
            yield from self._iter_ffmpeg_samples(
                Path(video_path),
                video,
                ffmpeg_path,
                interval=interval,
                start=begin,
                end=stop,
                max_width=max_width,
            )
            return
        yield from self._iter_opencv_samples(
            video_path,
            video,
            interval=interval,
            start=begin,
            end=stop,
            max_width=max_width,
        )

    def _iter_ffmpeg_samples(
        self,
        video_path,
        video,
        ffmpeg_path,
        *,
        interval,
        start,
        end,
        max_width,
    ):
        source_width = int(video.get("width", 0))
        source_height = int(video.get("height", 0))
        if source_width <= 0 or source_height <= 0:
            raise ValueError("Video dimensions are invalid")
        target_width = source_width
        if max_width is not None:
            target_width = min(source_width, max(2, int(max_width)))
        target_width -= target_width % 2
        target_height = max(
            2,
            int(round(source_height * target_width / source_width)),
        )
        target_height -= target_height % 2
        rate = 1.0 / float(interval)
        command = [
            str(ffmpeg_path),
            "-hide_banner",
            "-loglevel",
            "error",
            "-nostdin",
            "-ss",
            f"{start:.6f}",
            "-i",
            str(video_path),
            "-t",
            f"{end - start:.6f}",
            "-an",
            "-sn",
            "-dn",
            "-vf",
            (
                f"fps={rate:.12g},"
                f"scale={target_width}:{target_height}:flags=fast_bilinear"
            ),
            "-pix_fmt",
            "bgr24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        creation_flags = (
            subprocess.CREATE_NO_WINDOW
            if hasattr(subprocess, "CREATE_NO_WINDOW")
            else 0
        )
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags,
        )
        frame_size = target_width * target_height * 3
        frame_index = 0
        try:
            if process.stdout is None:
                raise RuntimeError("FFmpeg stdout pipe is unavailable")
            while True:
                data = process.stdout.read(frame_size)
                if not data:
                    break
                while len(data) < frame_size:
                    remainder = process.stdout.read(frame_size - len(data))
                    if not remainder:
                        break
                    data += remainder
                if len(data) != frame_size:
                    raise RuntimeError("FFmpeg returned an incomplete video frame")
                frame = np.frombuffer(data, dtype=np.uint8).reshape(
                    target_height,
                    target_width,
                    3,
                )
                timestamp = min(start + frame_index * interval, end)
                yield frame.copy(), round(timestamp, 6)
                frame_index += 1
            stderr = (
                process.stderr.read().decode("utf-8", errors="replace")
                if process.stderr is not None
                else ""
            )
            return_code = process.wait()
            if return_code != 0:
                raise RuntimeError(
                    f"FFmpeg sampling failed ({return_code}): {stderr.strip()}"
                )
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def _iter_opencv_samples(
        self,
        video_path,
        video,
        *,
        interval,
        start,
        end,
        max_width,
    ):
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise ValueError(f"Cannot open video file: {video_path}")
        fps = float(video.get("fps", 0.0))
        if not np.isfinite(fps) or fps <= 0:
            capture.release()
            raise ValueError("Video FPS is invalid")
        first_frame = max(0, int(round(start * fps)))
        final_frame = max(first_frame, int(math.ceil(end * fps)))
        sample_step = max(1, int(round(interval * fps)))
        capture.set(cv2.CAP_PROP_POS_FRAMES, first_frame)
        try:
            for source_index in range(first_frame, final_frame):
                ok = capture.grab()
                if not ok:
                    break
                if (source_index - first_frame) % sample_step != 0:
                    continue
                ok, frame = capture.retrieve()
                if not ok:
                    continue
                if max_width and frame.shape[1] > int(max_width):
                    width = int(max_width)
                    height = max(
                        2,
                        int(round(frame.shape[0] * width / frame.shape[1])),
                    )
                    frame = cv2.resize(
                        frame,
                        (width, height),
                        interpolation=cv2.INTER_AREA,
                    )
                yield frame, round(source_index / fps, 6)
        finally:
            capture.release()

    def has_audio_track(self, video_path):
        try:
            ffprobe_path = shutil.which('ffprobe')
            if not ffprobe_path:
                return False
            cmd = [
                ffprobe_path,
                '-v', 'error',
                '-select_streams', 'a',
                '-show_entries', 'stream=codec_type',
                '-of', 'json',
                str(video_path),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='backslashreplace',
            )

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

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return info

        fps = cap.get(cv2.CAP_PROP_FPS)
        info['fps'] = float(fps) if np.isfinite(fps) and fps > 0 else 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        info['duration'] = frame_count / info['fps'] if info['fps'] > 0 else 0.0
        info['width'] = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        info['height'] = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        cap.release()

        info['has_audio'] = self.has_audio_track(video_path)

        return info

    def _find_ffmpeg(self):
        ffmpeg_path = shutil.which('ffmpeg')
        if ffmpeg_path:
            return ffmpeg_path

        return None

    def save_frame(self, frame, output_path):
        if not cv2.imwrite(str(output_path), frame):
            raise OSError(f"Cannot write frame: {output_path}")

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
