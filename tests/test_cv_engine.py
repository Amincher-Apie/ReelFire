import unittest
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_TEST_ULTRALYTICS_DIR = (
    Path(tempfile.gettempdir()) / "reelfire-ultralytics-tests"
)
_TEST_ULTRALYTICS_DIR.mkdir(parents=True, exist_ok=True)
os.environ["YOLO_CONFIG_DIR"] = str(_TEST_ULTRALYTICS_DIR)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cv_engine.video_processor import VideoProcessor
from cv_engine.yolo_detector import YoloDetector
from cv_engine.highlight_extractor import HighlightExtractor
from cv_engine.highlight_scorer import HighlightScorer
from cv_engine.model_registry import ModelRegistry
from cv_engine.candidate_selector import (
    build_overlapping_windows,
    calculate_activity,
    score_activity_window,
    select_candidate_windows,
)
from services.analysis_service import (
    _merge_overlapping_segments,
    _refine_window_segments_with_tracking,
    analyze_video,
)

class TestVideoProcessor(unittest.TestCase):
    def test_iter_sample_chunks_bounds_frames_by_time_window(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "chunks.avi"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                2.0,
                (16, 16),
            )
            self.assertTrue(writer.isOpened())
            for value in range(12):
                writer.write(
                    np.full((16, 16, 3), value * 10, dtype=np.uint8)
                )
            writer.release()

            chunks = list(
                VideoProcessor().iter_sample_chunks(
                    video_path,
                    interval=1.0,
                    chunk_duration=2.0,
                )
            )

        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk["frames"]) <= 2 for chunk in chunks))
        self.assertEqual(
            [chunk["index"] for chunk in chunks],
            [0, 1, 2],
        )

    def test_iter_sample_windows_preserves_absolute_timestamps(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "windows.avi"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                2.0,
                (16, 16),
            )
            self.assertTrue(writer.isOpened())
            for value in range(16):
                writer.write(
                    np.full((16, 16, 3), value * 10, dtype=np.uint8)
                )
            writer.release()

            chunks = list(
                VideoProcessor().iter_sample_windows(
                    video_path,
                    [
                        {"start": 1.0, "end": 3.0},
                        {"start": 5.0, "end": 7.0},
                    ],
                    interval=1.0,
                    max_width=16,
                )
            )

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["timestamps"], [1.0, 2.0])
        self.assertEqual(chunks[1]["timestamps"], [5.0, 6.0])
        self.assertTrue(all(len(chunk["frames"]) == 2 for chunk in chunks))

    def test_iter_sample_windows_can_preserve_priority_order(self):
        import cv2
        import numpy as np

        with tempfile.TemporaryDirectory() as temporary:
            video_path = Path(temporary) / "priority-windows.avi"
            writer = cv2.VideoWriter(
                str(video_path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                2.0,
                (16, 16),
            )
            self.assertTrue(writer.isOpened())
            for value in range(16):
                writer.write(
                    np.full((16, 16, 3), value * 10, dtype=np.uint8)
                )
            writer.release()

            chunks = list(
                VideoProcessor().iter_sample_windows(
                    video_path,
                    [
                        {"start": 5.0, "end": 7.0},
                        {"start": 1.0, "end": 3.0},
                    ],
                    interval=1.0,
                    max_width=16,
                    preserve_order=True,
                )
            )

        self.assertEqual(chunks[0]["timestamps"], [5.0, 6.0])
        self.assertEqual(chunks[1]["timestamps"], [1.0, 2.0])

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
    def test_missing_model_has_clear_error(self):
        with self.assertRaisesRegex(FileNotFoundError, "Model file not found"):
            YoloDetector("models/definitely-missing.pt")

    def test_detect_frames(self):
        if not Path("models/yolo11n.pt").is_file():
            self.skipTest("models/yolo11n.pt is not present in the Git repository")
        detector = YoloDetector()

        import cv2
        test_frame = cv2.imread('tests/test_image.jpg')

        if test_frame is not None:
            results = detector.detect(test_frame)
            self.assertIsInstance(results, list)

    def test_detect_frames_uses_bounded_micro_batches(self):
        class FakeModel:
            names = {0: "object"}

            def __init__(self):
                self.batch_sizes = []

            def predict(self, *, source, **_kwargs):
                self.batch_sizes.append(len(source))
                return list(source)

        detector = YoloDetector.__new__(YoloDetector)
        detector.model = FakeModel()
        detector.confidence_threshold = 0.35
        detector.batch_size = 2
        detector._parse_result = lambda result: [result]

        results = detector.detect_frames(["a", "b", "c", "d", "e"])

        self.assertEqual(detector.model.batch_sizes, [2, 2, 1])
        self.assertEqual(results, [["a"], ["b"], ["c"], ["d"], ["e"]])

    def test_parse_tracking_result_includes_track_id(self):
        class Scalar:
            def __init__(self, value):
                self.value = value

            def item(self):
                return self.value

            def __float__(self):
                return float(self.value)

            def __int__(self):
                return int(self.value)

        class Values:
            def __init__(self, value):
                self.value = value

            def __getitem__(self, _index):
                return self

            def tolist(self):
                return self.value

        class Box:
            xyxy = Values([1.0, 2.0, 11.0, 22.0])
            conf = [Scalar(0.9)]
            cls = [Scalar(0)]

        class Boxes:
            id = [Scalar(42)]

            def __iter__(self):
                return iter([Box()])

        detector = YoloDetector.__new__(YoloDetector)
        detector.model = type("Model", (), {"names": {0: "enemy"}})()

        detections = detector._parse_result(
            type("Result", (), {"boxes": Boxes()})(),
            include_track_id=True,
        )

        self.assertEqual(detections[0]["track_id"], 42)
        self.assertEqual(detections[0]["bbox"], [1.0, 2.0, 11.0, 22.0])

    def test_associate_detections_reuses_existing_yolo_boxes(self):
        detector = YoloDetector.__new__(YoloDetector)
        frames = [
            [
                {
                    "class": "enemy",
                    "class_id": 0,
                    "confidence": 0.9,
                    "bbox": [10.0 + offset, 10.0, 30.0 + offset, 40.0],
                }
            ]
            for offset in (0.0, 1.0, 2.0)
        ]

        associated = detector.associate_detections(
            frames,
            sample_fps=2.0,
        )

        track_ids = [
            detections[0].get("track_id")
            for detections in associated
        ]
        self.assertTrue(all(track_id is not None for track_id in track_ids))
        self.assertEqual(len(set(track_ids)), 1)
        self.assertNotIn("track_id", frames[0][0])


class TestWindowTracking(unittest.TestCase):
    def test_refines_inside_window_and_keeps_segments_disjoint(self):
        segments = [
            {"id": "a", "start": 10.0, "end": 15.0, "duration": 5.0},
            {"id": "b", "start": 20.0, "end": 25.0, "duration": 5.0},
        ]
        samples = [
            {
                "timestamp": timestamp,
                "objects": [
                    {
                        "track_id": 1,
                        "class": "enemy",
                        "confidence": 0.9,
                        "bbox": [10.0, 20.0, 30.0, 60.0],
                    }
                ],
            }
            for timestamp in (16.0, 16.5, 18.5, 19.0)
        ]

        summary = _refine_window_segments_with_tracking(
            segments,
            samples,
            30.0,
            {"enemy"},
            {
                "tracking_margin_seconds": 5.0,
                "tracking_pre_roll_seconds": 5.0,
                "tracking_post_roll_seconds": 5.0,
            },
            {
                "enabled": True,
                "status": "completed",
                "scope_id": "chunk_0001",
                "sample_interval": 0.5,
            },
        )

        self.assertEqual(segments[0]["end"], 17.5)
        self.assertEqual(segments[1]["start"], 17.5)
        self.assertLessEqual(segments[0]["end"], segments[1]["start"])
        self.assertEqual(summary["refined_segment_count"], 2)
        self.assertEqual(
            segments[0]["tracking"]["tracks"][0]["track_key"],
            "chunk_0001:enemy:1",
        )

    def test_failed_window_tracking_preserves_boundaries(self):
        segments = [
            {"id": "a", "start": 10.0, "end": 20.0, "duration": 10.0},
        ]

        _refine_window_segments_with_tracking(
            segments,
            [],
            30.0,
            {"enemy"},
            {},
            {
                "enabled": True,
                "status": "failed",
                "scope_id": "chunk_0001",
                "sample_interval": 0.5,
            },
        )

        self.assertEqual((segments[0]["start"], segments[0]["end"]), (10.0, 20.0))
        self.assertEqual(segments[0]["tracking"]["status"], "failed")


class TestCandidateSelector(unittest.TestCase):
    def test_build_overlapping_windows_uses_sixty_second_window_and_stride(self):
        windows = build_overlapping_windows(
            120.0,
            window_duration=60.0,
            stride=30.0,
        )

        self.assertEqual(
            [(item["start"], item["end"]) for item in windows],
            [
                (0.0, 60.0),
                (30.0, 90.0),
                (60.0, 120.0),
                (90.0, 120.0),
            ],
        )
        self.assertEqual(
            [
                (item["queue"], item["queue_index"])
                for item in windows
            ],
            [("q1", 0), ("q2", 0), ("q1", 1), ("q2", 1)],
        )

    def test_overlapping_segments_are_replaced_by_their_time_union(self):
        merged = _merge_overlapping_segments(
            [
                {
                    "id": "seg_c0001_01",
                    "start": 55.0,
                    "end": 60.0,
                    "duration": 5.0,
                    "score": 0.7,
                    "source_keyframes": ["kf_1"],
                },
                {
                    "id": "seg_c0002_01",
                    "start": 55.0,
                    "end": 65.0,
                    "duration": 10.0,
                    "score": 0.9,
                    "source_keyframes": ["kf_2"],
                },
                {
                    "id": "seg_c0003_01",
                    "start": 64.0,
                    "end": 68.0,
                    "duration": 4.0,
                    "score": 0.8,
                    "source_keyframes": ["kf_3"],
                },
                {
                    "id": "seg_c0004_01",
                    "start": 68.0,
                    "end": 70.0,
                    "duration": 2.0,
                    "score": 0.6,
                    "source_keyframes": [],
                },
                {
                    "id": "seg_c0005_01",
                    "start": 75.0,
                    "end": 80.0,
                    "duration": 5.0,
                    "score": 0.5,
                    "source_keyframes": [],
                },
                {
                    "id": "seg_c0006_01",
                    "start": 75.0,
                    "end": 80.0,
                    "duration": 5.0,
                    "score": 0.4,
                    "source_keyframes": [],
                },
            ]
        )

        self.assertEqual(
            [(item["start"], item["end"]) for item in merged],
            [(55.0, 68.0), (68.0, 70.0), (75.0, 80.0)],
        )
        self.assertEqual(
            merged[0]["source_segment_ids"],
            ["seg_c0001_01", "seg_c0002_01", "seg_c0003_01"],
        )
        self.assertEqual(
            merged[0]["source_keyframes"],
            ["kf_1", "kf_2", "kf_3"],
        )
        self.assertEqual(
            merged[2]["source_segment_ids"],
            ["seg_c0005_01", "seg_c0006_01"],
        )

    def test_score_activity_window_blends_peak_and_average(self):
        samples = [
            {"timestamp": 0.0, "activity_score": 0.1},
            {"timestamp": 30.0, "activity_score": 0.9},
            {"timestamp": 60.0, "activity_score": 0.2},
        ]

        first = score_activity_window(samples, 0.0, 60.0)
        second = score_activity_window(samples, 30.0, 90.0)

        self.assertGreater(first, 0.1)
        self.assertGreater(second, first)

    def test_activity_uses_scene_motion_and_hud_changes(self):
        import numpy as np

        previous = np.zeros((90, 160, 3), dtype=np.uint8)
        current = previous.copy()
        current[0:40, 80:160] = 255

        empty = calculate_activity(previous, None)
        changed = calculate_activity(current, previous)

        self.assertEqual(empty["activity_score"], 0.0)
        self.assertGreater(changed["activity_score"], 0.0)
        self.assertGreater(changed["hud_change_score"], 0.0)

    def test_candidate_windows_are_distributed_and_budgeted(self):
        samples = [
            {
                "timestamp": float(timestamp),
                "activity_score": (timestamp % 90) / 90.0,
            }
            for timestamp in range(0, 600, 10)
        ]

        windows = select_candidate_windows(
            samples,
            600.0,
            target_duration=30.0,
            coverage_ratio=0.25,
            window_duration=16.0,
            bucket_duration=90.0,
        )

        coverage = sum(
            float(window["end"]) - float(window["start"])
            for window in windows
        )
        self.assertLessEqual(coverage, 150.001)
        self.assertGreater(coverage, 100.0)
        self.assertTrue(
            all(
                0.0 <= float(window["start"]) < float(window["end"]) <= 600.0
                for window in windows
            )
        )
        self.assertTrue(any(float(window["start"]) < 90.0 for window in windows))
        self.assertTrue(any(float(window["end"]) > 510.0 for window in windows))

    def test_long_video_candidate_budget_is_capped_by_target_duration(self):
        duration = 2854.25
        samples = [
            {
                "timestamp": float(timestamp),
                "activity_score": (timestamp % 90) / 90.0,
            }
            for timestamp in range(0, int(duration), 10)
        ]

        windows = select_candidate_windows(
            samples,
            duration,
            target_duration=30.0,
            coverage_ratio=0.25,
            window_duration=16.0,
            bucket_duration=90.0,
        )

        coverage = sum(
            float(window["end"]) - float(window["start"])
            for window in windows
        )
        self.assertLessEqual(coverage, 120.001)
        self.assertGreaterEqual(coverage, 112.0)


class TestModelRegistry(unittest.TestCase):
    def test_game_type_prefers_available_custom_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            official = root / "models" / "yolo11n.pt"
            custom_v3 = (
                root
                / "runs"
                / "detect"
                / "custom_fps_v3"
                / "weights"
                / "best.pt"
            )
            official.parent.mkdir(parents=True)
            custom_v3.parent.mkdir(parents=True)
            official.write_bytes(b"official")
            custom_v3.write_bytes(b"custom")

            registry = ModelRegistry(root)
            model, strategy, is_fallback = registry.resolve_by_game_type(
                "csgo"
            )

        self.assertEqual(model.model_id, "custom_v3")
        self.assertEqual(
            strategy["enemy_classes"],
            {"character_ct", "character_t"},
        )
        self.assertTrue(is_fallback)

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

    def test_calculate_segment_tags_uses_real_detections(self):
        scorer = HighlightScorer()
        samples = [
            {
                'timestamp': 5.0,
                'objects': [
                    {'class': 'person', 'confidence': 0.91},
                    {'class': 'person', 'confidence': 0.76},
                ],
            },
            {
                'timestamp': 20.0,
                'objects': [{'class': 'car', 'confidence': 0.88}],
            },
        ]
        tags = scorer.calculate_segment_tags(
            samples,
            [{'id': 'seg_001', 'start': 0.0, 'end': 10.0}],
        )
        self.assertEqual(tags['total_tags'], 1)
        self.assertEqual(tags['tags']['person']['count'], 2)
        self.assertEqual(tags['tags']['person']['segments'], ['seg_001'])
        self.assertEqual(tags['summary'], ['person(2)'])

    def test_generate_cover_prompt_does_not_invent_fps_events(self):
        scorer = HighlightScorer()
        prompt = scorer.generate_cover_prompt(
            {
                'timestamp': 12.5,
                'highlight_score': 0.82,
                'objects': [{'class': 'person'}, {'class': 'person'}],
            }
        )
        self.assertIn('person×2', prompt)
        self.assertIn('不虚构击杀或残局事件', prompt)


class TestHighlightExtractor(unittest.TestCase):
    def test_long_enemy_event_is_trimmed_around_peak(self):
        extractor = HighlightExtractor(
            smooth_frames=0,
            pre_buffer=0,
            post_buffer=0,
            max_duration=18.0,
        )
        frames = [
            {
                "timestamp": float(timestamp),
                "highlight_score": 1.0 if timestamp == 30 else 0.1,
                "detections": [
                    {
                        "class": "enemy",
                        "confidence": 0.9,
                        "bbox": [0, 0, 10, 10],
                    }
                ],
            }
            for timestamp in range(0, 61)
        ]

        result = extractor.extract(frames, 30.0, 61.0)

        self.assertEqual(len(result["segments"]), 1)
        segment = result["segments"][0]
        self.assertLessEqual(segment["duration"], 18.0)
        self.assertLessEqual(segment["start"], 30.0)
        self.assertGreaterEqual(segment["end"], 30.0)
        self.assertTrue(segment["trimmed_from_long_event"])

    def test_extract_returns_stable_ordered_multi_segments(self):
        extractor = HighlightExtractor(
            pre_buffer=0.0,
            post_buffer=0.0,
            smooth_frames=0,
            merge_gap=0.5,
        )
        frames = [
            {'timestamp': 0.0, 'detections': []},
            {
                'timestamp': 1.0,
                'detections': [
                    {'class': 'enemy', 'confidence': 0.8, 'track_id': 1},
                ],
            },
            {
                'timestamp': 2.0,
                'detections': [
                    {'class': 'enemy', 'confidence': 0.9, 'track_id': 1},
                    {'class': 'enemy', 'confidence': 0.7, 'track_id': 2},
                ],
            },
            {'timestamp': 3.0, 'detections': []},
            {
                'timestamp': 8.0,
                'detections': [
                    {'class': 'enemy', 'confidence': 0.75, 'track_id': 3},
                ],
            },
            {'timestamp': 9.0, 'detections': []},
        ]

        result = extractor.extract(frames, fps=24.0, duration=12.0)
        segments = result['segments']

        self.assertEqual([item['id'] for item in segments], ['seg_001', 'seg_002'])
        self.assertEqual([item['order'] for item in segments], [1, 2])
        self.assertEqual(
            [(item['start'], item['end']) for item in segments],
            [(1.0, 3.0), (8.0, 9.0)],
        )
        self.assertGreater(segments[0]['score'], segments[1]['score'])
        self.assertTrue(
            all(0.0 <= item['score'] <= 1.0 for item in segments)
        )
        self.assertTrue(all(item['source_keyframes'] == [] for item in segments))
        self.assertEqual(
            [item['frames_with_enemy'] for item in segments],
            [2, 1],
        )
        self.assertTrue(
            all('kill_type' in item['evidence'] for item in segments)
        )
        self.assertEqual(result['stats']['total_segments'], 2)

    def test_extract_without_enemy_returns_empty_segments(self):
        extractor = HighlightExtractor(smooth_frames=0)
        result = extractor.extract(
            [
                {'timestamp': 0.0, 'detections': []},
                {
                    'timestamp': 1.0,
                    'detections': [
                        {'class': 'weapon', 'confidence': 0.9},
                    ],
                },
            ],
            fps=24.0,
            duration=2.0,
        )

        self.assertEqual(result['segments'], [])
        self.assertEqual(result['stats']['total_segments'], 0)


class TestAnalysisServiceMultiSegment(unittest.TestCase):
    def test_analysis_report_uses_extractor_multi_segments(self):
        import numpy as np

        frames = [np.zeros((16, 16, 3), dtype=np.uint8) for _ in range(30)]
        timestamps = [float(index) for index in range(30)]
        detections = [[] for _ in frames]
        for index in (3, 4, 20, 21):
            detections[index] = [
                {
                    'class': 'enemy',
                    'confidence': 0.9,
                    'bbox': [2, 2, 10, 10],
                    'track_id': index,
                }
            ]

        class FakeDetector:
            def __init__(self, *_args, **_kwargs):
                self.offset = 0

            def detect_frames(self, chunk_frames):
                start = self.offset
                self.offset += len(chunk_frames)
                return detections[start:self.offset]

        chunks = [
            {
                'index': 0,
                'start': 0.0,
                'end': 15.0,
                'frames': frames[:15],
                'timestamps': timestamps[:15],
                'total_chunks': 2,
            },
            {
                'index': 1,
                'start': 15.0,
                'end': 30.0,
                'frames': frames[15:],
                'timestamps': timestamps[15:],
                'total_chunks': 2,
            },
        ]
        progress_updates = []
        segment_payloads = []

        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            with (
                patch(
                    'cv_engine.video_processor.VideoProcessor.get_video_info',
                    return_value={
                        'duration': 30.0,
                        'width': 16,
                        'height': 16,
                        'fps': 1.0,
                    },
                ),
                patch(
                    'cv_engine.video_processor.VideoProcessor.iter_sample_chunks',
                    return_value=iter(chunks),
                ),
                patch('cv_engine.yolo_detector.YoloDetector', FakeDetector),
                patch('cv2.imwrite', return_value=True),
                patch(
                    'services.analysis_service._save_contact_sheet_from_keyframes',
                    return_value=False,
                ),
            ):
                report = analyze_video(
                    Path(temporary) / 'input.mp4',
                    job_dir,
                    {
                        'model_path': str(Path(temporary) / 'model.pt'),
                        'keyframes_per_chunk': 3,
                        'chunk_duration': 15.0,
                        'min_keyframe_gap': 2.0,
                    },
                    progress_callback=progress_updates.append,
                    segment_callback=segment_payloads.append,
                )

        segments = report['segments']
        self.assertGreaterEqual(len(segments), 2)
        self.assertEqual(
            [segment['id'] for segment in segments],
            [f'seg_{index:03d}' for index in range(1, len(segments) + 1)],
        )
        self.assertEqual(
            [segment['order'] for segment in segments],
            list(range(1, len(segments) + 1)),
        )
        self.assertEqual(
            report['recommended_clip']['segment_count'],
            len(segments),
        )
        self.assertEqual(report['analysis_mode'], 'streaming_chunks')
        self.assertEqual(len(report['analysis_chunks']), 2)
        self.assertTrue(
            all('evidence' in segment for segment in segments)
        )
        self.assertTrue(
            all('representative_keyframe' in segment for segment in segments)
        )
        self.assertTrue(all('thumbnail' in segment for segment in segments))
        self.assertEqual(
            report['model']['confidence_threshold'],
            0.35,
        )
        queued = progress_updates[0]
        self.assertEqual(
            [chunk['status'] for chunk in queued['chunks']],
            ['queued', 'queued'],
        )
        self.assertEqual(queued['video']['duration'], 30.0)
        first_completed = next(
            update
            for update in progress_updates
            if update['completed_chunks'] == 1
            and update['current_chunk'] is None
        )
        self.assertEqual(
            [chunk['status'] for chunk in first_completed['chunks']],
            ['completed', 'queued'],
        )
        self.assertTrue(
            all(
                segment['id'].startswith('seg_c0001_')
                for segment in first_completed['chunks'][0][
                    'provisional_segments'
                ]
            )
        )
        self.assertEqual(
            [item['stage'] for item in progress_updates][-1],
            'finalizing',
        )
        self.assertTrue(
            all('chunk_id' in frame for frame in report['keyframes'])
        )
        self.assertGreaterEqual(len(segment_payloads), 1)
        self.assertTrue(
            all(
                len(payload["segments"]) == 1
                and payload["segments"][0]["id"].startswith("seg_c")
                and payload["total_sampled_frames"] > 0
                for payload in segment_payloads
            )
        )

    def test_long_video_streams_overlapping_windows_into_yolo(self):
        import numpy as np

        timeline = []
        yolo_frame_count = 0

        class FakeDetector:
            def __init__(self, *_args, **_kwargs):
                pass

            def detect_frames(self, chunk_frames):
                nonlocal yolo_frame_count
                timeline.append("yolo")
                yolo_frame_count += len(chunk_frames)
                return [
                    [
                        {
                            "class": "enemy",
                            "confidence": 0.9,
                            "bbox": [2, 2, 10, 10],
                        }
                    ]
                    for _ in chunk_frames
                ]

            def associate_detections(
                self,
                detection_frames,
                **_kwargs,
            ):
                timeline.append("track")
                return [
                    [
                        {**detection, "track_id": 1}
                        for detection in detections
                    ]
                    for detections in detection_frames
                ]

        def fine_chunks(_self, _path, windows, **_kwargs):
            window = windows[0]
            timeline.append(f"fine:{int(float(window['start']))}")
            timestamps = [
                float(window["start"]),
                min(float(window["start"]) + 30.0, float(window["end"]) - 0.5),
            ]
            yield {
                "index": 0,
                "start": float(window["start"]),
                "end": float(window["end"]),
                "frames": [
                    np.full((16, 16, 3), int(timestamp), dtype=np.uint8)
                    for timestamp in timestamps
                ],
                "timestamps": timestamps,
                "total_chunks": 1,
            }

        progress_updates = []
        segment_payloads = []

        with tempfile.TemporaryDirectory() as temporary:
            job_dir = Path(temporary)
            with (
                patch(
                    'cv_engine.video_processor.VideoProcessor.get_video_info',
                    return_value={
                        'duration': 120.0,
                        'width': 1920,
                        'height': 1080,
                        'fps': 30.0,
                    },
                ),
                patch(
                    'cv_engine.video_processor.VideoProcessor.iter_sample_chunks',
                    side_effect=AssertionError(
                        "long-video path must not run a coarse scan"
                    ),
                ),
                patch(
                    'cv_engine.video_processor.VideoProcessor.iter_sample_windows',
                    new=fine_chunks,
                ),
                patch('cv_engine.yolo_detector.YoloDetector', FakeDetector),
                patch('cv2.imwrite', return_value=True),
                patch(
                    'services.analysis_service._save_contact_sheet_from_keyframes',
                    return_value=False,
                ),
            ):
                report = analyze_video(
                    Path(temporary) / 'input.mp4',
                    job_dir,
                    {
                        'model_path': str(Path(temporary) / 'model.pt'),
                        'sample_interval': 30.0,
                        'target_duration': 30.0,
                        'two_stage_min_duration': 60.0,
                    },
                    progress_callback=progress_updates.append,
                    segment_callback=segment_payloads.append,
                )

        self.assertEqual(report['analysis_mode'], 'streaming_staggered_windows_v6')
        self.assertFalse(report['screening']['enabled'])
        self.assertEqual(
            report['screening']['strategy'],
            'direct_staggered_windows',
        )
        self.assertEqual(report['screening']['coarse_sample_count'], 0)
        self.assertEqual(report['screening']['candidate_window_count'], 4)
        self.assertEqual(
            report['screening']['processing_order'],
            'staggered_q1_q2',
        )
        self.assertEqual(report['screening']['window_duration'], 60.0)
        self.assertEqual(report['screening']['window_stride'], 30.0)
        self.assertEqual(yolo_frame_count, report['total_sampled_frames'])
        self.assertEqual(
            [item for item in timeline if item.startswith("fine:")],
            ["fine:0", "fine:30", "fine:60", "fine:90"],
        )
        self.assertEqual(
            [
                item
                for item in timeline
                if item == "track"
            ],
            ["track", "track", "track", "track"],
        )
        for index, item in enumerate(timeline):
            if item == "track":
                self.assertGreater(index, 0)
                self.assertEqual(timeline[index - 1], "yolo")
                if index + 1 < len(timeline):
                    self.assertTrue(
                        timeline[index + 1].startswith("fine:")
                    )
        self.assertEqual(progress_updates[0]['stage'], 'sampling')
        self.assertEqual(progress_updates[0]['total_chunks'], 4)
        self.assertEqual(report["tracking"]["window_count"], 4)
        self.assertEqual(
            report["tracking"]["mode"],
            "per_window_detection_association",
        )
        first_completed = next(
            update
            for update in progress_updates
            if update.get("completed_chunks") == 1
        )
        self.assertEqual(first_completed["provisional_segment_count"], 0)
        first_pair_completed = next(
            update
            for update in progress_updates
            if update.get("completed_chunks") == 2
            and update.get("stage") == "detecting"
        )
        self.assertGreaterEqual(
            first_pair_completed["provisional_segment_count"],
            1,
        )
        self.assertTrue(
            all(
                float(segment["duration"])
                == round(
                    float(segment["end"]) - float(segment["start"]),
                    3,
                )
                for segment in report["segments"]
            )
        )
        self.assertTrue(
            all(
                float(current["end"]) <= float(following["start"])
                for current, following in zip(
                    report["segments"],
                    report["segments"][1:],
                )
            )
        )
        self.assertTrue(
            all('eta_seconds' in update for update in progress_updates)
        )
        self.assertGreaterEqual(len(segment_payloads), 1)
        self.assertEqual(len(segment_payloads), len(report["segments"]))
        self.assertEqual(
            len({payload["segments"][0]["id"] for payload in segment_payloads}),
            len(segment_payloads),
        )
        self.assertTrue(
            all(
                payload["segments"][0]["id"].startswith("seg_union_")
                for payload in segment_payloads
            )
        )


if __name__ == '__main__':
    unittest.main()
