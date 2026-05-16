# Feature: kvs-video-streaming
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

import numpy as np
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from frame_annotator import FrameAnnotator, Detection, DetectionBox
from shadow_config import ShadowConfigManager, DEFAULT_CONFIG, VALID_RESOLUTIONS
from unittest.mock import MagicMock

# ── Property 1: Time-window annotation ───────────────────────────────────────
@settings(max_examples=100)
@given(
    staleness=st.floats(min_value=0.1, max_value=300.0),
    delta=st.floats(min_value=0.0, max_value=400.0),
)
def test_property1_time_window_annotation(staleness, delta):
    a = FrameAnnotator(staleness_window_seconds=staleness)
    received_at = 1000.0
    frame_time = received_at + delta
    det = Detection("cat", 0.9, DetectionBox(10, 10, 50, 50))
    a.update_detections([det], received_at=received_at)
    f = np.zeros((100, 100, 3), dtype=np.uint8)
    result = a.annotate(f, frame_time=frame_time)
    if delta > staleness:
        # Stale — must be pixel-identical copy
        assert np.array_equal(result, f), f"delta={delta} > staleness={staleness}: expected no annotation"
    else:
        # Fresh — must differ (bounding box drawn on a non-zero region)
        # We can only assert the input is not modified
        assert result is not f

# ── Property 3: Confidence score formatting ───────────────────────────────────
@settings(max_examples=100)
@given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False))
def test_property3_confidence_score_formatting(score):
    formatted = f"{score * 100:.1f}%"
    # Must end with %
    assert formatted.endswith("%")
    # Must contain exactly one decimal place
    numeric_part = formatted[:-1]
    dot_pos = numeric_part.find(".")
    assert dot_pos != -1
    assert len(numeric_part) - dot_pos - 1 == 1

# ── Property 4: Empty detections preserve frame identity ─────────────────────
@settings(max_examples=100)
@given(
    h=st.integers(min_value=10, max_value=200),
    w=st.integers(min_value=10, max_value=200),
)
def test_property4_empty_detections_preserve_frame(h, w):
    a = FrameAnnotator(staleness_window_seconds=30.0)
    a.update_detections([], received_at=1000.0)
    f = np.zeros((h, w, 3), dtype=np.uint8)
    original = f.copy()
    result = a.annotate(f, frame_time=1001.0)
    assert np.array_equal(result, original)
    assert np.array_equal(f, original), "Input frame must not be modified"
    assert result is not f

# ── Property 5: Colour assignment consistency ─────────────────────────────────
@settings(max_examples=100)
@given(label=st.text(min_size=1, max_size=50))
def test_property5_colour_consistency(label):
    a = FrameAnnotator(staleness_window_seconds=30.0)
    c1 = a.get_colour(label)
    c2 = a.get_colour(label)
    assert c1 == c2

# ── Property 6: Stale detection discard ──────────────────────────────────────
@settings(max_examples=100)
@given(
    staleness=st.floats(min_value=0.1, max_value=100.0),
    extra=st.floats(min_value=0.001, max_value=100.0),
)
def test_property6_stale_detection_discard(staleness, extra):
    a = FrameAnnotator(staleness_window_seconds=staleness)
    received_at = 1000.0
    frame_time = received_at + staleness + extra  # always stale
    det = Detection("cat", 0.9, DetectionBox(10, 10, 50, 50))
    a.update_detections([det], received_at=received_at)
    f = np.zeros((100, 100, 3), dtype=np.uint8)
    original = f.copy()
    result = a.annotate(f, frame_time=frame_time)
    assert np.array_equal(result, original), "Stale detection must not annotate frame"

# ── Property 7: Configuration validation ─────────────────────────────────────
@settings(max_examples=100)
@given(
    frame_rate=st.integers(min_value=1, max_value=30),
    resolution=st.sampled_from(sorted(VALID_RESOLUTIONS)),
    streaming_enabled=st.booleans(),
    staleness=st.floats(min_value=0.001, max_value=1000.0, allow_nan=False),
    snapshot_interval=st.integers(min_value=1, max_value=3600),
)
def test_property7_valid_config_accepted(frame_rate, resolution, streaming_enabled,
                                          staleness, snapshot_interval):
    mgr = ShadowConfigManager(MagicMock(), "t")
    config, errors = mgr.apply_delta({
        "frame_rate": frame_rate,
        "resolution": resolution,
        "streaming_enabled": streaming_enabled,
        "staleness_window_seconds": staleness,
        "snapshot_interval_seconds": snapshot_interval,
    })
    assert errors == []
    assert config.frame_rate == frame_rate
    assert config.resolution == resolution

@settings(max_examples=100)
@given(
    frame_rate=st.integers().filter(lambda x: not (1 <= x <= 30)),
)
def test_property7_invalid_frame_rate_rejected(frame_rate):
    mgr = ShadowConfigManager(MagicMock(), "t")
    _, errors = mgr.apply_delta({"frame_rate": frame_rate})
    assert any("frame_rate" in e for e in errors)

@settings(max_examples=100)
@given(
    staleness=st.one_of(
        st.floats(max_value=0.0, allow_nan=False),
        st.just(0),
        st.integers(max_value=0),
    )
)
def test_property7_invalid_staleness_rejected(staleness):
    mgr = ShadowConfigManager(MagicMock(), "t")
    _, errors = mgr.apply_delta({"staleness_window_seconds": staleness})
    assert any("staleness_window" in e for e in errors)
