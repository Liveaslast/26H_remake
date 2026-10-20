"""Independent inference, optical-flow and refinement state behind one detector API."""

from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from ballbeam.app.detector_setup import select_backend, warm_up_detector
from ballbeam.vision.detection_runtime.detector import (
    AdaptiveBallDetector, AdaptiveBallDetectorConfig, CircleRefinementCache,
    ModelInference, OpticalFlowTracker,
)
from ballbeam.vision.detection_runtime.models import CircleRefinement
from ballbeam.vision.detection_runtime.preprocessing import letterbox, normalize_image_size


class Boxes:
    def __init__(self, boxes, confidence=None, classes=None):
        self.xyxy = np.asarray(boxes).reshape(-1, 4)
        self.conf = np.asarray([.9] * len(boxes) if confidence is None else confidence)
        self.cls = np.asarray([0] * len(boxes) if classes is None else classes)

    def __len__(self):
        return len(self.xyxy)


def model(boxes):
    prediction = SimpleNamespace(boxes=boxes,
        timings=SimpleNamespace(preprocess_ms=1, inference_ms=2, postprocess_ms=3))
    return Mock(predict=Mock(return_value=[prediction]))


def circle(frame, box, config):
    center = ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)
    return CircleRefinement(True, center, 5, .8, .1, 20, 30, "ok")


class DetectorComponentTests(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 200, 3), np.uint8)
        self.config = AdaptiveBallDetectorConfig(detection_interval=1, track_scale=1)

    def test_inference_normalizes_backend_results_without_temporal_state(self):
        backend = model(Boxes([[10, 20, 30, 40], [0, 0, 10, 10], [0, 0, 0, 10]],
                              confidence=[.9, .1, .9]))
        inference = ModelInference(self.config, backend)
        candidates, timings = inference.predict(self.frame)
        self.assertEqual(candidates, [((10, 20, 30, 40), .9, 0)])
        self.assertEqual((timings.preprocess_ms, timings.inference_ms, timings.postprocess_ms), (1, 2, 3))
        self.assertFalse(hasattr(inference, "_cache"))
        self.assertFalse(hasattr(inference, "_flow_tracks"))

    def test_empty_model_output_is_valid_empty_detection(self):
        inference = ModelInference(self.config, model(Boxes([])))
        candidates, timings = inference.predict(self.frame)
        self.assertEqual(candidates, [])
        self.assertEqual(timings.inference_ms, 2)

    def test_disabled_refinement_uses_bbox_and_never_calls_refiner(self):
        refiner = Mock(side_effect=AssertionError("refinement must stay off"))
        detector = AdaptiveBallDetector(replace(self.config, enable_circle_refinement=False),
            model=model(Boxes([[10, 20, 30, 40]])), circle_refiner=refiner)
        result = detector.detect(self.frame)
        self.assertEqual(result.balls[0].center_px, (20, 30))
        self.assertEqual(result.balls[0].source, "yolo_box")
        self.assertEqual(result.inference_ms, 2)
        self.assertEqual(result.timings.inference_ms, 2)
        refiner.assert_not_called()

    def test_refinement_reuse_period_and_reset_are_independent_of_model(self):
        refiner = Mock(side_effect=circle)
        cache = CircleRefinementCache(replace(self.config, refine_interval=3), refiner)
        candidate = [((40, 40, 60, 60), .9, 0)]
        results = [cache.refine(self.frame, candidate, i) for i in range(1, 5)]
        self.assertEqual([r.balls[0].source for r in results],
                         ["ransac", "cached_ransac", "cached_ransac", "ransac"])
        self.assertEqual(refiner.call_count, 2)
        self.assertEqual(results[-1].periodic_refined_count, 1)
        cache.reset()
        cache.refine(self.frame, candidate, 5)
        self.assertEqual(refiner.call_count, 3)

    def test_refinement_cache_expires_on_missing_detections(self):
        refiner = Mock(side_effect=circle)
        cache = CircleRefinementCache(replace(self.config, cache_max_missed_frames=1), refiner)
        candidate = [((40, 40, 60, 60), .9, 0)]
        cache.refine(self.frame, candidate, 1)
        cache.refine(self.frame, [], 2)
        cache.refine(self.frame, [], 3)
        self.assertEqual(cache.refine(self.frame, candidate, 4).balls[0].source, "ransac")
        self.assertEqual(refiner.call_count, 2)

    def test_failed_refinement_keeps_existing_bbox_fallback(self):
        refiner = Mock(return_value=CircleRefinement(False, (0, 0), 0, 0, None, 0, 0, "failed"))
        cache = CircleRefinementCache(self.config, refiner)
        result = cache.refine(self.frame, [((40, 40, 60, 60), .9, 0)], 1)
        self.assertEqual(result.balls[0].source, "yolo_box")
        self.assertEqual(result.ransac_failure_count, 1)

    def test_flow_tracks_translation_without_calling_model(self):
        rng = np.random.default_rng(5)
        frame = rng.integers(0, 256, (100, 200, 3), dtype=np.uint8)
        detector = AdaptiveBallDetector(replace(self.config, detection_interval=3,
                                                enable_circle_refinement=False),
                                        model=model(Boxes([[50, 30, 80, 60]])))
        first = detector.detect(frame)
        tracked = detector.detect(np.roll(frame, 1, axis=1))
        self.assertEqual(tracked.frame_source, "tracked")
        self.assertFalse(tracked.correction_requested)
        self.assertAlmostEqual(tracked.balls[0].center_px[0], first.balls[0].center_px[0] + 1, delta=.15)
        detector.inference._model.predict.assert_called_once()

    def test_failed_flow_requests_new_inference_on_next_frame(self):
        backend = model(Boxes([[10, 20, 30, 40]]))
        detector = AdaptiveBallDetector(replace(self.config, detection_interval=10,
                                                enable_circle_refinement=False), model=backend)
        detector.detect(self.frame)
        failed = detector.detect(self.frame)
        self.assertTrue(failed.correction_requested)
        self.assertEqual(backend.predict.call_count, 1)
        self.assertEqual(detector.detect(self.frame).frame_source, "detected")
        self.assertEqual(backend.predict.call_count, 2)

    def test_reset_clears_history_but_preserves_loaded_model(self):
        backend = model(Boxes([[10, 20, 30, 40]]))
        detector = AdaptiveBallDetector(self.config, model=backend, circle_refiner=circle)
        detector.detect(self.frame)
        detector.reset_tracking()
        self.assertIs(detector.inference._model, backend)
        self.assertEqual(detector.detect(self.frame).frame_index, 1)
        self.assertEqual(backend.predict.call_count, 2)

    def test_pipeline_accepts_independent_stages_without_loading_backend(self):
        inference, flow, refinement = Mock(), Mock(), Mock()
        template = AdaptiveBallDetector(replace(self.config, enable_circle_refinement=False),
                                       model=model(Boxes([[10, 20, 30, 40]])))
        detection = template.detect(self.frame)
        inference.predict.return_value = ([], detection.timings)
        refinement.refine.return_value = detection
        flow.track.return_value = replace(detection, frame_source="tracked")
        config = replace(self.config, detection_interval=2)
        with patch("ballbeam.vision.detection_runtime.detector.ModelInference") as create_backend:
            detector = AdaptiveBallDetector(config, inference=inference, flow=flow, refinement=refinement)
            self.assertEqual(detector.detect(self.frame).frame_source, "detected")
            self.assertEqual(detector.detect(self.frame).frame_source, "tracked")
        create_backend.assert_not_called()
        self.assertEqual(inference.predict.call_count, 1)
        flow.initialize.assert_called_once()
        refinement.refine.assert_called_once()

    def test_uninitialized_flow_reports_failure_without_inference(self):
        flow = OpticalFlowTracker(self.config)
        result = flow.track(self.frame, 7)
        self.assertEqual(result.frame_index, 7)
        self.assertEqual(result.correction_reason, "not_initialized")
        self.assertTrue(result.correction_requested)

    def test_backend_selection_does_not_probe_ncnn_for_hailort(self):
        with patch("ballbeam.vision.detection_runtime.ncnn_backend.native_ncnn_available") as probe:
            self.assertEqual(select_backend("hailort", "cpp"), "hailort")
        probe.assert_not_called()

    def test_warmup_discards_tracking_but_skip_does_not_touch_detector(self):
        detector = Mock()
        warm_up_detector(detector, (640, 128))
        self.assertEqual(detector.detect.call_args.args[0].shape, (128, 640, 3))
        detector.reset_tracking.assert_called_once()
        detector.reset_mock()
        self.assertEqual(warm_up_detector(detector, (640, 128), skip=True), 0)
        self.assertEqual(detector.mock_calls, [])

    def test_shared_preprocessing_preserves_padding_and_scale(self):
        self.assertEqual(normalize_image_size(32), (32, 32))
        image, ratio, padding = letterbox(self.frame, (128, 640))
        self.assertEqual(image.shape, (128, 640, 3))
        self.assertEqual(ratio, 1.28)
        self.assertEqual(padding, (192, 0))
        self.assertTrue(np.all(image[:, :192] == 114))
        self.assertTrue(image.flags.c_contiguous)

    def test_ncnn_adapter_uses_shared_preprocessing_and_restores_coordinates(self):
        from ballbeam.vision.detection_runtime import ncnn_backend
        native = Mock()
        native.infer.return_value = dict(boxes=[[204.8, 25.6, 230.4, 51.2, .9, 0]],
                                         inference_ms=2)
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(ncnn_backend, "_NativeNcnnBackend", return_value=native), \
             patch.object(Path, "exists", return_value=True):
            backend = ncnn_backend.CppNcnnBackend(directory)
            result = backend.predict(source=self.frame, imgsz=(128, 640), conf=.25, iou=.7)[0]
        self.assertEqual(native.infer.call_args.args[0].shape, (128, 640, 3))
        np.testing.assert_allclose(result.boxes.xyxy[0], [10, 20, 30, 40], atol=1e-4)
        self.assertEqual(result.timings.inference_ms, 2)
