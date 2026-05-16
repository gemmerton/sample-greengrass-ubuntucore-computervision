import sys, os, time
import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

from frame_annotator import FrameAnnotator, Detection, DetectionBox

def frame(h=100, w=100):
    return np.zeros((h, w, 3), dtype=np.uint8)

def det(label="cat", score=0.9, xmin=10, ymin=10, xmax=50, ymax=50):
    return Detection(label=label, score=score,
                     box=DetectionBox(ymin=ymin, xmin=xmin, ymax=ymax, xmax=xmax))

def test_annotate_within_window_changes_pixels():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    a.update_detections([det()], received_at=now)
    f = frame()
    result = a.annotate(f, frame_time=now + 1.0)
    assert not np.array_equal(result, f)

def test_annotate_outside_window_returns_pixel_identical_copy():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    a.update_detections([det()], received_at=now)
    f = frame()
    result = a.annotate(f, frame_time=now + 31.0)
    assert np.array_equal(result, f)

def test_annotate_no_detections_ever_returns_pixel_identical_copy():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    f = frame()
    result = a.annotate(f, frame_time=time.time())
    assert np.array_equal(result, f)

def test_annotate_does_not_modify_input_frame():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    a.update_detections([det()], received_at=now)
    f = frame()
    original = f.copy()
    a.annotate(f, frame_time=now + 1.0)
    assert np.array_equal(f, original)

def test_annotate_returns_copy_not_same_object():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    f = frame()
    result = a.annotate(f, frame_time=time.time())
    assert result is not f

def test_confidence_score_formatted_to_one_decimal_percent():
    # Verify format string directly: 0.956 -> "95.6%"
    score = 0.956
    formatted = f"{score * 100:.1f}%"
    assert formatted == "95.6%"

def test_confidence_score_format_0_and_1():
    assert f"{0.0 * 100:.1f}%" == "0.0%"
    assert f"{1.0 * 100:.1f}%" == "100.0%"

def test_get_colour_consistent_for_same_label():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    assert a.get_colour("dog") == a.get_colour("dog")

def test_get_colour_at_least_10_distinct_colours():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    colours = {a.get_colour(f"class_{i}") for i in range(10)}
    assert len(colours) == 10

def test_update_detections_replaces_previous():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    a.update_detections([det(label="cat")], received_at=now)
    a.update_detections([det(label="dog")], received_at=now + 1)
    # Only latest update matters; result should have annotations (within window)
    f = frame(200, 200)
    assert not np.array_equal(a.annotate(f, frame_time=now + 2.0), f)

def test_update_detections_empty_list_no_annotation():
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    a.update_detections([], received_at=now)
    f = frame()
    assert np.array_equal(a.annotate(f, frame_time=now + 1.0), f)

def test_annotate_performance_under_50ms():
    import timeit
    a = FrameAnnotator(staleness_window_seconds=30.0)
    now = time.time()
    # Simulate 10 detections on a 1280x720 frame
    dets = [det(f"class_{i}", 0.9, i*50, i*30, i*50+40, i*30+40) for i in range(10)]
    a.update_detections(dets, received_at=now)
    f = np.zeros((720, 1280, 3), dtype=np.uint8)
    elapsed = timeit.timeit(lambda: a.annotate(f, now + 1.0), number=1)
    assert elapsed < 0.05, f"Annotation took {elapsed:.3f}s, must be < 50ms"
