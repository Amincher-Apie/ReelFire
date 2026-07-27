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
from services.analysis_service import analyze_video

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


if __name__ == '__main__':
    unittest.main()
