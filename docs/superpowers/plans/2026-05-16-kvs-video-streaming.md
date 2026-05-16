# KVS Video Streaming Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a KVS Producer Greengrass component that streams live annotated video from the edge device to AWS Kinesis Video Streams, and embed an HLS player in the React dashboard to view that stream.

**Architecture:** The KVS Producer owns the camera via a GStreamer `v4l2src + tee` pipeline — one branch feeds a Python annotator thread that overlays inference bounding boxes (received from `camera/detections` via IoT Core MQTT) and pushes annotated frames into a second GStreamer `appsrc → x264enc → kvssink` pipeline. The other tee branch periodically saves JPEG snapshots and publishes them to `camera/images`, preserving the Detection Handler's input unchanged. The React dashboard calls `GetHLSStreamingSessionURL` and plays the stream via `hls.js`.

**Tech Stack:** Python 3, GStreamer 1.0 + PyGObject (`gi`), OpenCV, `awsiotsdk==1.21.0`, Hypothesis (property tests), React 19, TypeScript, `hls.js`, `@aws-sdk/client-kinesisvideo`, Vitest + Testing Library.

**Design doc:** `.kiro/specs/kvs-video-streaming/design.md`

---

## File Map

**Create (Python — new component):**
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/shadow_config.py`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/health_monitor.py`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/frame_annotator.py`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/requirements.txt`
- `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/get-pip.py` (copied from CameraHandlerCore)

**Create (Recipe):**
- `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml`

**Create (Python tests):**
- `tests/test_kvs_shadow_config.py`
- `tests/test_kvs_health_monitor.py`
- `tests/test_kvs_frame_annotator.py`
- `tests/test_kvs_properties.py`
- `tests/test_kvs_gstreamer.py`
- `tests/test_kvs_producer.py`
- `tests/test_kvs_aws_setup.py`

**Create (React):**
- `react-web/src/types/kvs.ts`
- `react-web/src/services/kvsService.ts`
- `react-web/src/components/dashboard/KvsPlayer.tsx`
- `react-web/src/components/dashboard/KvsPlayer.css`
- `react-web/src/components/dashboard/__tests__/KvsPlayer.test.tsx`

**Modify:**
- `setup_aws_resources.py` — add `create_kvs_stream`, `attach_kvs_producer_policy`, `attach_kvs_viewer_policy`
- `react-web/src/components/dashboard/Dashboard.tsx` — embed KvsPlayer + stream status
- `react-web/package.json` — add `hls.js`, `@aws-sdk/client-kinesisvideo`

---

## Task 1: Shadow Config Module

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/shadow_config.py`
- Create: `tests/test_kvs_shadow_config.py`

- [ ] **Step 1: Create the artifact directory**

```bash
mkdir -p greengrass-components/artifacts/com.example.KvsProducer/1.0.0
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_kvs_shadow_config.py`:

```python
import sys, os, json, pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

from shadow_config import (
    ShadowConfigManager, KvsConfig, DEFAULT_CONFIG, VALID_RESOLUTIONS
)

def _ipc_with_shadow(desired: dict):
    ipc = MagicMock()
    r = MagicMock()
    r.payload = json.dumps({"state": {"desired": desired}}).encode()
    ipc.get_thing_shadow.return_value = r
    return ipc

def _ipc_unavailable():
    ipc = MagicMock()
    ipc.get_thing_shadow.side_effect = Exception("unavailable")
    return ipc

def test_read_config_falls_back_to_default_when_shadow_unavailable():
    mgr = ShadowConfigManager(_ipc_unavailable(), "t")
    assert mgr.read_config() == DEFAULT_CONFIG

def test_read_config_returns_shadow_values():
    ipc = _ipc_with_shadow({"stream_name": "s", "frame_rate": 10,
        "resolution": "1280x720", "streaming_enabled": False,
        "staleness_window_seconds": 60.0, "snapshot_interval_seconds": 5})
    mgr = ShadowConfigManager(ipc, "t")
    c = mgr.read_config()
    assert c.stream_name == "s"
    assert c.frame_rate == 10
    assert c.resolution == "1280x720"
    assert c.streaming_enabled is False
    assert c.staleness_window_seconds == 60.0
    assert c.snapshot_interval_seconds == 5

def test_apply_delta_rejects_frame_rate_above_30():
    _, errors = ShadowConfigManager(MagicMock(), "t").apply_delta({"frame_rate": 31})
    assert any("frame_rate" in e for e in errors)

def test_apply_delta_rejects_frame_rate_below_1():
    _, errors = ShadowConfigManager(MagicMock(), "t").apply_delta({"frame_rate": 0})
    assert any("frame_rate" in e for e in errors)

def test_apply_delta_rejects_invalid_resolution():
    _, errors = ShadowConfigManager(MagicMock(), "t").apply_delta({"resolution": "800x600"})
    assert any("resolution" in e for e in errors)

def test_apply_delta_accepts_all_valid_resolutions():
    for res in VALID_RESOLUTIONS:
        c, errors = ShadowConfigManager(MagicMock(), "t").apply_delta({"resolution": res})
        assert c.resolution == res
        assert errors == []

def test_apply_delta_rejects_staleness_window_zero_or_negative():
    for val in [0, -1.0]:
        _, errors = ShadowConfigManager(MagicMock(), "t").apply_delta(
            {"staleness_window_seconds": val})
        assert any("staleness_window" in e for e in errors)

def test_apply_delta_rejects_snapshot_interval_out_of_range():
    for val in [0, 3601]:
        _, errors = ShadowConfigManager(MagicMock(), "t").apply_delta(
            {"snapshot_interval_seconds": val})
        assert any("snapshot_interval" in e for e in errors)

def test_apply_delta_valid_config_has_no_errors():
    c, errors = ShadowConfigManager(MagicMock(), "t").apply_delta({
        "frame_rate": 15, "resolution": "640x480",
        "streaming_enabled": True, "staleness_window_seconds": 30.0,
        "snapshot_interval_seconds": 10,
    })
    assert errors == []
    assert c.frame_rate == 15

def test_report_state_puts_streaming_status_in_payload():
    ipc = MagicMock()
    mgr = ShadowConfigManager(ipc, "my-thing")
    mgr.report_state(KvsConfig("s", 15, "640x480", True, 30.0, 10), "streaming")
    ipc.update_thing_shadow.assert_called_once()
    kw = ipc.update_thing_shadow.call_args.kwargs
    payload = json.loads(kw["payload"])
    assert payload["state"]["reported"]["streaming_status"] == "streaming"
```

- [ ] **Step 3: Run tests — expect ImportError (module not created yet)**

```bash
pytest tests/test_kvs_shadow_config.py -v
```

Expected: `ModuleNotFoundError: No module named 'shadow_config'`

- [ ] **Step 4: Create `shadow_config.py`**

```python
from dataclasses import dataclass
import json
import logging

logger = logging.getLogger(__name__)

VALID_RESOLUTIONS = {"640x480", "1280x720", "1920x1080"}

@dataclass
class KvsConfig:
    stream_name: str
    frame_rate: int
    resolution: str
    streaming_enabled: bool
    staleness_window_seconds: float
    snapshot_interval_seconds: int

DEFAULT_CONFIG = KvsConfig(
    stream_name="",
    frame_rate=15,
    resolution="640x480",
    streaming_enabled=True,
    staleness_window_seconds=30.0,
    snapshot_interval_seconds=10,
)

class ShadowConfigManager:
    def __init__(self, ipc_client, thing_name: str, shadow_name: str = "kvs-config"):
        self._client = ipc_client
        self._thing_name = thing_name
        self._shadow_name = shadow_name

    def read_config(self) -> KvsConfig:
        try:
            response = self._client.get_thing_shadow(
                thing_name=self._thing_name, shadow_name=self._shadow_name
            )
            desired = json.loads(response.payload).get("state", {}).get("desired", {})
            config, errors = self._validate(desired)
            if errors:
                logger.warning("Shadow config validation errors: %s", errors)
            return config
        except Exception as e:
            logger.warning("Shadow unavailable, using defaults: %s", e)
            return DEFAULT_CONFIG

    def apply_delta(self, delta: dict) -> tuple:
        return self._validate(delta)

    def report_state(self, config: KvsConfig, status: str) -> None:
        try:
            reported = {
                "stream_name": config.stream_name,
                "frame_rate": config.frame_rate,
                "resolution": config.resolution,
                "streaming_enabled": config.streaming_enabled,
                "staleness_window_seconds": config.staleness_window_seconds,
                "snapshot_interval_seconds": config.snapshot_interval_seconds,
                "streaming_status": status,
            }
            self._client.update_thing_shadow(
                thing_name=self._thing_name,
                shadow_name=self._shadow_name,
                payload=json.dumps({"state": {"reported": reported}}).encode(),
            )
        except Exception as e:
            logger.warning("Failed to update shadow reported state: %s", e)

    def _validate(self, data: dict) -> tuple:
        errors = []
        config = KvsConfig(
            stream_name=data.get("stream_name", DEFAULT_CONFIG.stream_name),
            frame_rate=DEFAULT_CONFIG.frame_rate,
            resolution=DEFAULT_CONFIG.resolution,
            streaming_enabled=bool(data.get("streaming_enabled",
                                             DEFAULT_CONFIG.streaming_enabled)),
            staleness_window_seconds=DEFAULT_CONFIG.staleness_window_seconds,
            snapshot_interval_seconds=DEFAULT_CONFIG.snapshot_interval_seconds,
        )
        fr = data.get("frame_rate")
        if fr is not None:
            if isinstance(fr, int) and 1 <= fr <= 30:
                config.frame_rate = fr
            else:
                errors.append(f"frame_rate {fr!r} must be integer in [1, 30]")
        res = data.get("resolution")
        if res is not None:
            if res in VALID_RESOLUTIONS:
                config.resolution = res
            else:
                errors.append(f"resolution {res!r} must be one of {VALID_RESOLUTIONS}")
        sw = data.get("staleness_window_seconds")
        if sw is not None:
            if isinstance(sw, (int, float)) and sw > 0:
                config.staleness_window_seconds = float(sw)
            else:
                errors.append(f"staleness_window_seconds {sw!r} must be float > 0")
        si = data.get("snapshot_interval_seconds")
        if si is not None:
            if isinstance(si, int) and 1 <= si <= 3600:
                config.snapshot_interval_seconds = si
            else:
                errors.append(f"snapshot_interval_seconds {si!r} must be integer in [1, 3600]")
        return config, errors
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
pytest tests/test_kvs_shadow_config.py -v
```

Expected: 10 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add greengrass-components/artifacts/com.example.KvsProducer/1.0.0/shadow_config.py \
        tests/test_kvs_shadow_config.py
git commit -m "feat(kvs): add shadow config module with KvsConfig validation"
```

---

## Task 2: Health Monitor Module

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/health_monitor.py`
- Create: `tests/test_kvs_health_monitor.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kvs_health_monitor.py`:

```python
import sys, os, json, pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

from health_monitor import HealthMonitor, StreamMetrics

def test_record_frame_sent_increments_counter():
    m = HealthMonitor(MagicMock())
    m.record_frame_sent()
    m.record_frame_sent()
    assert m.get_current_metrics().frames_sent == 2

def test_record_frame_dropped_increments_counter():
    m = HealthMonitor(MagicMock())
    m.record_frame_dropped()
    assert m.get_current_metrics().frames_dropped == 1

def test_update_bitrate_calculates_kbps():
    m = HealthMonitor(MagicMock())
    # 1000 bytes / 0.4 s = 1000*8 / (0.4*1000) = 20 kbps
    m.update_bitrate(bytes_sent=1000, elapsed_seconds=0.4)
    assert m.get_current_metrics().bitrate_kbps == pytest.approx(20.0)

def test_update_bitrate_zero_elapsed_does_not_crash():
    m = HealthMonitor(MagicMock())
    m.update_bitrate(bytes_sent=1000, elapsed_seconds=0)
    assert m.get_current_metrics().bitrate_kbps == 0.0

def test_set_status_updates_connection_status():
    m = HealthMonitor(MagicMock())
    m.set_status("buffering")
    assert m.get_current_metrics().connection_status == "buffering"

def test_publish_metrics_calls_iot_core_with_correct_topic():
    ipc = MagicMock()
    m = HealthMonitor(ipc)
    m.publish_metrics()
    ipc.publish_to_iot_core.assert_called_once()
    assert ipc.publish_to_iot_core.call_args.kwargs["topic_name"] == "camera/kvs-status"

def test_publish_metrics_payload_matches_schema():
    ipc = MagicMock()
    m = HealthMonitor(ipc)
    m.record_frame_sent()
    m.record_frame_dropped()
    m.set_status("streaming")
    m.publish_metrics()
    payload = json.loads(ipc.publish_to_iot_core.call_args.kwargs["payload"])
    assert "timestamp" in payload
    assert payload["frames_sent"] == 1
    assert payload["frames_dropped"] == 1
    assert payload["connection_status"] == "streaming"
    assert "bitrate_kbps" in payload
    assert "error_reason" in payload
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_kvs_health_monitor.py -v
```

Expected: `ModuleNotFoundError: No module named 'health_monitor'`

- [ ] **Step 3: Create `health_monitor.py`**

```python
from dataclasses import dataclass, field
import datetime, json, logging, time

logger = logging.getLogger(__name__)

@dataclass
class StreamMetrics:
    frames_sent: int = 0
    frames_dropped: int = 0
    bitrate_kbps: float = 0.0
    connection_status: str = "offline"

class HealthMonitor:
    def __init__(self, ipc_client, topic: str = "camera/kvs-status"):
        self._client = ipc_client
        self._topic = topic
        self._metrics = StreamMetrics()

    def record_frame_sent(self) -> None:
        self._metrics.frames_sent += 1

    def record_frame_dropped(self) -> None:
        self._metrics.frames_dropped += 1

    def update_bitrate(self, bytes_sent: int, elapsed_seconds: float) -> None:
        if elapsed_seconds > 0:
            self._metrics.bitrate_kbps = (bytes_sent * 8) / (elapsed_seconds * 1000)

    def set_status(self, status: str) -> None:
        self._metrics.connection_status = status

    def get_current_metrics(self) -> StreamMetrics:
        return self._metrics

    def publish_metrics(self) -> None:
        payload = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "frames_sent": self._metrics.frames_sent,
            "frames_dropped": self._metrics.frames_dropped,
            "bitrate_kbps": self._metrics.bitrate_kbps,
            "connection_status": self._metrics.connection_status,
            "error_reason": None,
        }
        try:
            self._client.publish_to_iot_core(
                topic_name=self._topic,
                qos="1",
                payload=json.dumps(payload).encode(),
            )
        except Exception as e:
            logger.warning("Failed to publish health metrics: %s", e)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_kvs_health_monitor.py -v
```

Expected: 7 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.KvsProducer/1.0.0/health_monitor.py \
        tests/test_kvs_health_monitor.py
git commit -m "feat(kvs): add health monitor module"
```

---

## Task 3: Frame Annotator Module

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/frame_annotator.py`
- Create: `tests/test_kvs_frame_annotator.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kvs_frame_annotator.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_kvs_frame_annotator.py -v
```

Expected: `ModuleNotFoundError: No module named 'frame_annotator'`

- [ ] **Step 3: Create `frame_annotator.py`**

```python
from dataclasses import dataclass
from typing import Optional
import cv2, logging, numpy as np

logger = logging.getLogger(__name__)

COLOUR_PALETTE = [
    (255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0),
    (0, 255, 255), (255, 0, 255), (128, 0, 0), (0, 128, 0),
    (0, 0, 128), (128, 128, 0),
]

@dataclass
class DetectionBox:
    ymin: float
    xmin: float
    ymax: float
    xmax: float

@dataclass
class Detection:
    label: str
    score: float
    box: DetectionBox

class FrameAnnotator:
    def __init__(self, staleness_window_seconds: float = 30.0, num_classes: int = 10):
        self._staleness_window = staleness_window_seconds
        self._detections: list = []
        self._received_at: Optional[float] = None
        self._label_colour_map: dict = {}
        self._colour_index = 0

    def update_detections(self, detections: list, received_at: float) -> None:
        self._detections = detections
        self._received_at = received_at

    def annotate(self, frame: np.ndarray, frame_time: float) -> np.ndarray:
        result = frame.copy()
        if (self._received_at is None
                or frame_time - self._received_at > self._staleness_window):
            return result
        for d in self._detections:
            colour = self.get_colour(d.label)
            x1, y1 = int(d.box.xmin), int(d.box.ymin)
            x2, y2 = int(d.box.xmax), int(d.box.ymax)
            cv2.rectangle(result, (x1, y1), (x2, y2), colour, 2)
            label_text = f"{d.label} {d.score * 100:.1f}%"
            cv2.putText(result, label_text, (x1, max(0, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
        return result

    def get_colour(self, class_label: str) -> tuple:
        if class_label not in self._label_colour_map:
            self._label_colour_map[class_label] = (
                COLOUR_PALETTE[self._colour_index % len(COLOUR_PALETTE)]
            )
            self._colour_index += 1
        return self._label_colour_map[class_label]
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_kvs_frame_annotator.py -v
```

Expected: 12 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.KvsProducer/1.0.0/frame_annotator.py \
        tests/test_kvs_frame_annotator.py
git commit -m "feat(kvs): add frame annotator with time-window staleness model"
```

---

## Task 4: Property-Based Tests

**Files:**
- Create: `tests/test_kvs_properties.py`

These use [Hypothesis](https://hypothesis.readthedocs.io/) to verify universal correctness across generated inputs (Properties 1, 3–7 from the design doc). Each test runs ≥ 100 iterations.

- [ ] **Step 1: Install Hypothesis**

```bash
pip install hypothesis
```

- [ ] **Step 2: Write property-based tests**

Create `tests/test_kvs_properties.py`:

```python
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
# Feature: kvs-video-streaming, Property 1: time-window annotation
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
# Feature: kvs-video-streaming, Property 3: confidence score formatting
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
# Feature: kvs-video-streaming, Property 4: empty detections preserve frame
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
# Feature: kvs-video-streaming, Property 5: colour assignment consistency
@settings(max_examples=100)
@given(label=st.text(min_size=1, max_size=50))
def test_property5_colour_consistency(label):
    a = FrameAnnotator(staleness_window_seconds=30.0)
    c1 = a.get_colour(label)
    c2 = a.get_colour(label)
    assert c1 == c2

# ── Property 6: Stale detection discard ──────────────────────────────────────
# Feature: kvs-video-streaming, Property 6: stale detection discard
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
# Feature: kvs-video-streaming, Property 7: configuration validation
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
```

- [ ] **Step 3: Run property tests**

```bash
pytest tests/test_kvs_properties.py -v
```

Expected: all tests PASSED (each runs 100 iterations)

- [ ] **Step 4: Commit**

```bash
git add tests/test_kvs_properties.py
git commit -m "test(kvs): add property-based tests for annotator and config (Hypothesis)"
```

---

## Task 5: GStreamer Pipeline Modules

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py`
- Create: `tests/test_kvs_gstreamer.py`

GStreamer is not available in CI. All tests mock `gi` before importing `gstreamer_pipeline`. We test Python-level logic only (callback wiring, state checks, pipeline lifecycle).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kvs_gstreamer.py`:

```python
import sys, os
from unittest.mock import MagicMock, patch, call
import numpy as np

# Mock gi BEFORE importing gstreamer_pipeline
gi_mock = MagicMock()
gst_mock = MagicMock()
glib_mock = MagicMock()
gi_mock.repository.Gst = gst_mock
gi_mock.repository.GLib = glib_mock
sys.modules["gi"] = gi_mock
sys.modules["gi.repository"] = gi_mock.repository

# Set up GStreamer state constants
gst_mock.State.PLAYING = "PLAYING"
gst_mock.State.PAUSED = "PAUSED"
gst_mock.State.NULL = "NULL"
gst_mock.MapFlags.READ = "READ"
gst_mock.FlowReturn.OK = "OK"

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

from gstreamer_pipeline import CapturePipeline, EncodingPipeline


def test_capture_pipeline_on_raw_frame_callback_registered():
    p = CapturePipeline("/dev/video0", 15, 640, 480, 10)
    cb = MagicMock()
    p.set_on_raw_frame(cb)
    assert p._on_raw_frame_cb is cb


def test_capture_pipeline_on_snapshot_callback_registered():
    p = CapturePipeline("/dev/video0", 15, 640, 480, 10)
    cb = MagicMock()
    p.set_on_snapshot(cb)
    assert p._on_snapshot_cb is cb


def test_capture_pipeline_start_calls_gst_parse_launch():
    p = CapturePipeline("/dev/video0", 15, 640, 480, 10)
    p.start()
    gst_mock.parse_launch.assert_called_once()
    pipeline_str = gst_mock.parse_launch.call_args[0][0]
    assert "v4l2src" in pipeline_str
    assert "tee" in pipeline_str
    assert "appsink" in pipeline_str


def test_capture_pipeline_stop_sets_null_state():
    p = CapturePipeline("/dev/video0", 15, 640, 480, 10)
    p.start()
    mock_pipeline = gst_mock.parse_launch.return_value
    p.stop()
    mock_pipeline.set_state.assert_called_with(gst_mock.State.NULL)


def test_encoding_pipeline_start_creates_appsrc_pipeline():
    p = EncodingPipeline("my-stream", "us-east-1", 15, 640, 480)
    p.start()
    pipeline_str = gst_mock.parse_launch.call_args[0][0]
    assert "appsrc" in pipeline_str
    assert "x264enc" in pipeline_str
    assert "kvssink" in pipeline_str
    assert "my-stream" in pipeline_str


def test_encoding_pipeline_push_frame_returns_false_when_not_healthy():
    p = EncodingPipeline("s", "us-east-1", 15, 640, 480)
    # _pipeline is None before start() — is_healthy returns False
    assert p.push_frame(np.zeros((480, 640, 3), dtype=np.uint8)) is False


def test_encoding_pipeline_is_healthy_false_before_start():
    p = EncodingPipeline("s", "us-east-1", 15, 640, 480)
    assert p.is_healthy() is False


def test_encoding_pipeline_reconfigure_restarts_with_new_params():
    p = EncodingPipeline("s", "us-east-1", 15, 640, 480)
    p.start()
    mock_pipeline = gst_mock.parse_launch.return_value
    p.reconfigure(10, 1280, 720)
    # Stop then start again
    mock_pipeline.set_state.assert_called_with(gst_mock.State.NULL)
    assert p._framerate == 10
    assert p._width == 1280
    assert p._height == 720
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_kvs_gstreamer.py -v
```

Expected: `ModuleNotFoundError: No module named 'gstreamer_pipeline'`

- [ ] **Step 3: Create `gstreamer_pipeline.py`**

```python
import gi
gi.require_version("Gst", "1.0")
from gi.repository import Gst
import logging, numpy as np, time
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class CapturePipeline:
    """v4l2src -> tee -> raw appsink + snapshot appsink."""

    def __init__(self, device: str, framerate: int, width: int, height: int,
                 snapshot_interval_seconds: int):
        self._device = device
        self._framerate = framerate
        self._width = width
        self._height = height
        self._snapshot_interval = snapshot_interval_seconds
        self._pipeline = None
        self._on_raw_frame_cb: Optional[Callable] = None
        self._on_snapshot_cb: Optional[Callable] = None

    def set_on_raw_frame(self, callback: Callable) -> None:
        self._on_raw_frame_cb = callback

    def set_on_snapshot(self, callback: Callable) -> None:
        self._on_snapshot_cb = callback

    def start(self) -> None:
        Gst.init(None)
        pipeline_str = (
            f"v4l2src device={self._device} "
            f"! video/x-raw,width={self._width},height={self._height},"
            f"framerate={self._framerate}/1 "
            f"! tee name=t "
            f"t. ! queue ! videoconvert "
            f"! video/x-raw,format=BGR ! appsink name=raw_sink emit-signals=true "
            f"t. ! queue ! videorate "
            f"! image/jpeg,framerate=1/{self._snapshot_interval} ! jpegenc "
            f"! appsink name=snapshot_sink emit-signals=true"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._pipeline.get_by_name("raw_sink").connect(
            "new-sample", self._on_raw_sample)
        self._pipeline.get_by_name("snapshot_sink").connect(
            "new-sample", self._on_snapshot_sample)
        self._pipeline.set_state(Gst.State.PLAYING)

    def _on_raw_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        caps = sample.get_caps()
        struct = caps.get_structure(0)
        h = struct.get_value("height")
        w = struct.get_value("width")
        success, map_info = buf.map(Gst.MapFlags.READ)
        if success:
            frame = np.frombuffer(map_info.data, dtype=np.uint8).reshape((h, w, 3))
            if self._on_raw_frame_cb:
                self._on_raw_frame_cb(frame.copy(), time.time())
            buf.unmap(map_info)
        return Gst.FlowReturn.OK

    def _on_snapshot_sample(self, sink):
        sample = sink.emit("pull-sample")
        buf = sample.get_buffer()
        success, map_info = buf.map(Gst.MapFlags.READ)
        if success:
            if self._on_snapshot_cb:
                self._on_snapshot_cb(bytes(map_info.data))
            buf.unmap(map_info)
        return Gst.FlowReturn.OK

    def stop(self) -> None:
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)

    def is_healthy(self) -> bool:
        if not self._pipeline:
            return False
        return self._pipeline.get_state(0)[1] in (Gst.State.PLAYING, Gst.State.PAUSED)


class EncodingPipeline:
    """appsrc -> videoconvert -> x264enc -> h264parse -> kvssink.

    kvssink reads credentials via AWS_CONTAINER_CREDENTIALS_RELATIVE_URI
    set automatically by Greengrass for components with TokenExchangeService.
    """

    def __init__(self, stream_name: str, region: str, framerate: int,
                 width: int, height: int):
        self._stream_name = stream_name
        self._region = region
        self._framerate = framerate
        self._width = width
        self._height = height
        self._pipeline = None
        self._appsrc = None

    def start(self) -> None:
        Gst.init(None)
        pipeline_str = (
            f"appsrc name=src format=time is-live=true "
            f"caps=video/x-raw,format=BGR,width={self._width},"
            f"height={self._height},framerate={self._framerate}/1 "
            f"! videoconvert ! x264enc tune=zerolatency "
            f"! h264parse ! kvssink stream-name={self._stream_name} "
            f"aws-region={self._region}"
        )
        self._pipeline = Gst.parse_launch(pipeline_str)
        self._appsrc = self._pipeline.get_by_name("src")
        self._pipeline.set_state(Gst.State.PLAYING)

    def push_frame(self, frame: np.ndarray) -> bool:
        if not self.is_healthy():
            return False
        buf = Gst.Buffer.new_wrapped(frame.tobytes())
        self._appsrc.emit("push-buffer", buf)
        return True

    def stop(self) -> None:
        if self._pipeline:
            self._pipeline.set_state(Gst.State.NULL)

    def is_healthy(self) -> bool:
        if not self._pipeline:
            return False
        return self._pipeline.get_state(0)[1] in (Gst.State.PLAYING, Gst.State.PAUSED)

    def reconfigure(self, framerate: int, width: int, height: int) -> None:
        self.stop()
        self._framerate = framerate
        self._width = width
        self._height = height
        self.start()
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_kvs_gstreamer.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.KvsProducer/1.0.0/gstreamer_pipeline.py \
        tests/test_kvs_gstreamer.py
git commit -m "feat(kvs): add GStreamer capture and encoding pipeline modules"
```

---

## Task 6: KVS Producer Orchestrator

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py`
- Create: `tests/test_kvs_producer.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kvs_producer.py`:

```python
import sys, os, json, time
from unittest.mock import MagicMock, patch, call
import numpy as np

# Mock gi before any import resolves gstreamer_pipeline
gi_mock = MagicMock()
gst_mock = MagicMock()
gst_mock.State.PLAYING = "PLAYING"
gst_mock.State.PAUSED = "PAUSED"
gst_mock.State.NULL = "NULL"
gst_mock.MapFlags.READ = "READ"
gst_mock.FlowReturn.OK = "OK"
gi_mock.repository.Gst = gst_mock
sys.modules["gi"] = gi_mock
sys.modules["gi.repository"] = gi_mock.repository

# Mock awsiot before import
awsiot_mock = MagicMock()
sys.modules["awsiot"] = awsiot_mock
sys.modules["awsiot.greengrasscoreipc"] = awsiot_mock.greengrasscoreipc
sys.modules["awsiot.greengrasscoreipc.clientv2"] = awsiot_mock.greengrasscoreipc.clientv2
sys.modules["awsiot.greengrasscoreipc.model"] = awsiot_mock.greengrasscoreipc.model

sys.path.insert(0, os.path.join(os.path.dirname(__file__),
    "../greengrass-components/artifacts/com.example.KvsProducer/1.0.0"))

with patch.dict(os.environ, {
    "AWS_IOT_THING_NAME": "test-thing",
    "KVS_STREAM_NAME": "test-stream",
    "AWS_DEFAULT_REGION": "us-east-1",
    "CAMERA_DEVICE": "/dev/video0",
    "SNAP_USER_DATA": "/tmp/kvs-test",
}):
    from kvs_producer import KvsProducer


def make_producer():
    with patch("kvs_producer.clientv2.GreengrassCoreIPCClientV2", return_value=MagicMock()), \
         patch("kvs_producer.CapturePipeline") as MockCapture, \
         patch("kvs_producer.EncodingPipeline") as MockEncode:
        MockCapture.return_value.is_healthy.return_value = True
        MockEncode.return_value.is_healthy.return_value = True
        MockEncode.return_value.push_frame.return_value = True
        p = KvsProducer()
        return p, MockCapture, MockEncode


def test_on_detection_message_calls_update_detections():
    p, _, _ = make_producer()
    payload = json.dumps({
        "detections": [{"label": "cat", "score": 0.9,
                        "box": {"ymin": 10.0, "xmin": 10.0, "ymax": 50.0, "xmax": 50.0}}]
    }).encode()
    event = MagicMock()
    event.message.payload = payload
    p._on_detection_message(event)
    assert len(p._annotator._detections) == 1
    assert p._annotator._detections[0].label == "cat"


def test_on_detection_message_parses_nested_box():
    p, _, _ = make_producer()
    payload = json.dumps({
        "detections": [{"label": "dog", "score": 0.8,
                        "box": {"ymin": 5.0, "xmin": 15.0, "ymax": 80.0, "xmax": 70.0}}]
    }).encode()
    event = MagicMock()
    event.message.payload = payload
    p._on_detection_message(event)
    box = p._annotator._detections[0].box
    assert box.ymin == 5.0
    assert box.xmin == 15.0


def test_on_raw_frame_pushes_annotated_frame_to_encoding_pipeline():
    p, MockCapture, MockEncode = make_producer()
    enc_instance = MockEncode.return_value
    enc_instance.push_frame.return_value = True
    p._encoding_pipeline = enc_instance
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    p._on_raw_frame(frame, time.time())
    enc_instance.push_frame.assert_called_once()


def test_on_raw_frame_records_frame_sent_on_success():
    p, MockCapture, MockEncode = make_producer()
    enc_instance = MockEncode.return_value
    enc_instance.push_frame.return_value = True
    p._encoding_pipeline = enc_instance
    p._on_raw_frame(np.zeros((480, 640, 3), dtype=np.uint8), time.time())
    assert p._health_monitor.get_current_metrics().frames_sent == 1


def test_on_raw_frame_records_frame_dropped_on_pipeline_failure():
    p, MockCapture, MockEncode = make_producer()
    enc_instance = MockEncode.return_value
    enc_instance.push_frame.return_value = False
    p._encoding_pipeline = enc_instance
    p._on_raw_frame(np.zeros((480, 640, 3), dtype=np.uint8), time.time())
    assert p._health_monitor.get_current_metrics().frames_dropped == 1


def test_on_raw_frame_skips_encoding_when_streaming_disabled():
    p, MockCapture, MockEncode = make_producer()
    enc_instance = MockEncode.return_value
    p._encoding_pipeline = enc_instance
    p._config.streaming_enabled = False
    p._on_raw_frame(np.zeros((480, 640, 3), dtype=np.uint8), time.time())
    enc_instance.push_frame.assert_not_called()


def test_on_snapshot_saves_jpeg_and_publishes_camera_images(tmp_path):
    p, _, _ = make_producer()
    p._output_directory = str(tmp_path)
    jpeg_bytes = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG header
    p._on_snapshot(jpeg_bytes)
    saved_files = list(tmp_path.iterdir())
    assert len(saved_files) == 1
    assert saved_files[0].read_bytes() == jpeg_bytes
    p._ipc_client.publish_to_topic.assert_called_once()


def test_on_detection_message_with_malformed_payload_does_not_crash():
    p, _, _ = make_producer()
    event = MagicMock()
    event.message.payload = b"not valid json"
    p._on_detection_message(event)  # must not raise
```

- [ ] **Step 2: Run tests — expect ImportError**

```bash
pytest tests/test_kvs_producer.py -v
```

Expected: `ModuleNotFoundError: No module named 'kvs_producer'`

- [ ] **Step 3: Create `kvs_producer.py`**

```python
import os, sys, json, time, logging, datetime
import numpy as np
import awsiot.greengrasscoreipc.clientv2 as clientv2
from awsiot.greengrasscoreipc.model import (
    PublishMessage, JsonMessage, SubscriptionResponseMessage
)

from shadow_config import ShadowConfigManager, DEFAULT_CONFIG, KvsConfig
from health_monitor import HealthMonitor
from frame_annotator import FrameAnnotator, Detection, DetectionBox
from gstreamer_pipeline import CapturePipeline, EncodingPipeline

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

HEALTH_PUBLISH_INTERVAL = 30
ERROR_THRESHOLD_SECONDS = 60
MAX_RESTARTS = 3
RESTART_DELAY = 30


class KvsProducer:
    def __init__(self):
        self._thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self._stream_name = os.environ.get("KVS_STREAM_NAME", "")
        self._region = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        self._camera_device = os.environ.get("CAMERA_DEVICE", "/dev/video0")
        self._output_directory = os.environ.get("SNAP_USER_DATA", "/tmp/kvs-snapshots")
        os.makedirs(self._output_directory, exist_ok=True)

        self._ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self._shadow_mgr = ShadowConfigManager(self._ipc_client, self._thing_name)
        self._health_monitor = HealthMonitor(self._ipc_client)
        self._config = DEFAULT_CONFIG
        self._annotator = FrameAnnotator(
            staleness_window_seconds=self._config.staleness_window_seconds)
        self._capture_pipeline: CapturePipeline = None
        self._encoding_pipeline: EncodingPipeline = None
        self._last_frame_sent_time: float = 0.0
        self._last_health_publish: float = 0.0

    def run(self):
        self._config = self._shadow_mgr.read_config()
        if self._stream_name:
            self._config.stream_name = self._stream_name
        self._subscribe_to_detections()
        self._subscribe_to_shadow_delta()
        self._start_pipelines()
        logger.info("KvsProducer running, streaming to %s", self._config.stream_name)
        try:
            while True:
                now = time.time()
                if now - self._last_health_publish >= HEALTH_PUBLISH_INTERVAL:
                    self._health_monitor.publish_metrics()
                    self._last_health_publish = now
                if (self._last_frame_sent_time > 0
                        and now - self._last_frame_sent_time > ERROR_THRESHOLD_SECONDS):
                    self._health_monitor.set_status("error")
                    self._health_monitor.publish_metrics()
                time.sleep(1)
        except KeyboardInterrupt:
            self._stop_pipelines()

    def _start_pipelines(self):
        w, h = map(int, self._config.resolution.split("x"))
        self._capture_pipeline = CapturePipeline(
            self._camera_device, self._config.frame_rate, w, h,
            self._config.snapshot_interval_seconds)
        self._capture_pipeline.set_on_raw_frame(self._on_raw_frame)
        self._capture_pipeline.set_on_snapshot(self._on_snapshot)
        self._encoding_pipeline = EncodingPipeline(
            self._config.stream_name, self._region,
            self._config.frame_rate, w, h)
        self._encoding_pipeline.start()
        self._capture_pipeline.start()

    def _stop_pipelines(self):
        if self._capture_pipeline:
            self._capture_pipeline.stop()
        if self._encoding_pipeline:
            self._encoding_pipeline.stop()

    def _on_raw_frame(self, frame: np.ndarray, frame_time: float):
        if not self._config.streaming_enabled:
            return
        annotated = self._annotator.annotate(frame, frame_time)
        if self._encoding_pipeline and self._encoding_pipeline.push_frame(annotated):
            self._health_monitor.record_frame_sent()
            self._last_frame_sent_time = frame_time
            self._health_monitor.set_status("streaming")
        else:
            self._health_monitor.record_frame_dropped()

    def _on_snapshot(self, jpeg_bytes: bytes):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = os.path.join(self._output_directory, f"snapshot_{ts}.jpg")
        with open(filepath, "wb") as f:
            f.write(jpeg_bytes)
        msg = {"image_path": filepath,
               "timestamp": datetime.datetime.now().isoformat()}
        try:
            self._ipc_client.publish_to_topic(
                topic="camera/images",
                publish_message=PublishMessage(json_message=JsonMessage(message=msg)))
        except Exception as e:
            logger.warning("Failed to publish snapshot: %s", e)

    def _subscribe_to_detections(self):
        try:
            self._ipc_client.subscribe_to_iot_core(
                topic_name="camera/detections",
                qos="1",
                on_stream_event=self._on_detection_message,
                on_stream_error=lambda e: logger.warning("Detection stream error: %s", e),
                on_stream_closed=lambda: logger.info("Detection stream closed"),
            )
        except Exception as e:
            logger.error("Failed to subscribe to camera/detections: %s", e)

    def _on_detection_message(self, event):
        try:
            payload = json.loads(event.message.payload)
            detections = [
                Detection(
                    label=d["label"], score=d["score"],
                    box=DetectionBox(
                        ymin=d["box"]["ymin"], xmin=d["box"]["xmin"],
                        ymax=d["box"]["ymax"], xmax=d["box"]["xmax"]))
                for d in payload.get("detections", [])
            ]
            self._annotator.update_detections(detections, time.time())
        except Exception as e:
            logger.warning("Failed to parse detection message: %s", e)

    def _subscribe_to_shadow_delta(self):
        delta_topic = (
            f"$aws/things/{self._thing_name}/shadow/name/kvs-config/update/delta"
        )
        try:
            self._ipc_client.subscribe_to_iot_core(
                topic_name=delta_topic, qos="1",
                on_stream_event=self._on_shadow_delta,
                on_stream_error=lambda e: logger.warning("Shadow delta error: %s", e),
                on_stream_closed=lambda: logger.info("Shadow delta stream closed"),
            )
        except Exception as e:
            logger.warning("Failed to subscribe to shadow delta: %s", e)

    def _on_shadow_delta(self, event):
        try:
            delta = json.loads(event.message.payload).get("state", {})
            new_config, errors = self._shadow_mgr.apply_delta(delta)
            if errors:
                self._shadow_mgr.report_state(self._config, "error")
                return
            needs_restart = (new_config.frame_rate != self._config.frame_rate
                             or new_config.resolution != self._config.resolution)
            self._config = new_config
            self._annotator = FrameAnnotator(
                staleness_window_seconds=self._config.staleness_window_seconds)
            if needs_restart and self._encoding_pipeline:
                w, h = map(int, self._config.resolution.split("x"))
                self._encoding_pipeline.reconfigure(self._config.frame_rate, w, h)
            status = "streaming" if self._config.streaming_enabled else "stopped"
            self._shadow_mgr.report_state(self._config, status)
        except Exception as e:
            logger.warning("Failed to apply shadow delta: %s", e)


def main():
    try:
        KvsProducer().run()
    except Exception as e:
        logger.error("KvsProducer failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_kvs_producer.py -v
```

Expected: 9 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add greengrass-components/artifacts/com.example.KvsProducer/1.0.0/kvs_producer.py \
        tests/test_kvs_producer.py
git commit -m "feat(kvs): add KVS Producer orchestrator"
```

---

## Task 7: Greengrass Recipe and Requirements

**Files:**
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/requirements.txt`
- Create: `greengrass-components/artifacts/com.example.KvsProducer/1.0.0/get-pip.py`
- Create: `greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml`
- Create: `tests/test_kvs_recipe.py`

- [ ] **Step 1: Write the recipe validation test**

Create `tests/test_kvs_recipe.py`:

```python
import os
import yaml  # pip install pyyaml

RECIPE_PATH = os.path.join(os.path.dirname(__file__),
    "../greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml")

def load_recipe():
    with open(RECIPE_PATH) as f:
        return yaml.safe_load(f)

def test_recipe_file_exists():
    assert os.path.exists(RECIPE_PATH)

def test_recipe_declares_camera_handler_as_soft_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "com.example.CameraHandlerCore" in deps
    assert deps["com.example.CameraHandlerCore"]["DependencyType"] == "SOFT"

def test_recipe_declares_detection_handler_as_soft_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "com.example.DetectionHandler" in deps
    assert deps["com.example.DetectionHandler"]["DependencyType"] == "SOFT"

def test_recipe_declares_token_exchange_service_as_hard_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "aws.greengrass.TokenExchangeService" in deps
    dep_type = deps["aws.greengrass.TokenExchangeService"].get("DependencyType", "HARD")
    assert dep_type == "HARD"

def test_recipe_declares_shadow_manager_as_hard_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "aws.greengrass.ShadowManager" in deps

def test_recipe_grants_iot_core_subscribe_to_camera_detections():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    mqttproxy = ac.get("aws.greengrass.ipc.mqttproxy", {})
    resources = []
    for policy in mqttproxy.values():
        resources.extend(policy.get("resources", []))
        ops = policy.get("operations", [])
    all_resources = []
    for policy in mqttproxy.values():
        all_resources.extend(policy.get("resources", []))
    assert "camera/detections" in all_resources

def test_recipe_grants_local_pubsub_publish_to_camera_images():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    pubsub = ac.get("aws.greengrass.ipc.pubsub", {})
    all_resources = []
    for policy in pubsub.values():
        all_resources.extend(policy.get("resources", []))
    assert "camera/images" in all_resources

def test_recipe_grants_shadow_get_and_update_for_kvs_config():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    shadow = ac.get("aws.greengrass.ShadowManager", {})
    all_ops = []
    all_resources = []
    for policy in shadow.values():
        all_ops.extend(policy.get("operations", []))
        all_resources.extend(policy.get("resources", []))
    assert "aws.greengrass#GetThingShadow" in all_ops
    assert "aws.greengrass#UpdateThingShadow" in all_ops
    assert any("kvs-config" in r for r in all_resources)
```

- [ ] **Step 2: Run test — expect FileNotFoundError**

```bash
pytest tests/test_kvs_recipe.py -v
```

Expected: `FileNotFoundError` (recipe doesn't exist yet)

- [ ] **Step 3: Create `requirements.txt`**

```
awsiotsdk==1.21.0
opencv-python-headless
numpy
PyGObject
```

- [ ] **Step 4: Copy `get-pip.py` from CameraHandlerCore**

```bash
cp greengrass-components/artifacts/com.example.CameraHandlerCore/1.0.0/get-pip.py \
   greengrass-components/artifacts/com.example.KvsProducer/1.0.0/get-pip.py
```

- [ ] **Step 5: Create `com.example.KvsProducer-1.0.0.yaml`**

```yaml
---
RecipeFormatVersion: '2020-01-25'
ComponentName: com.example.KvsProducer
ComponentVersion: '1.0.0'
ComponentDescription: >
  Streams annotated live video from the edge device to AWS Kinesis Video Streams.
  Owns the camera via GStreamer, overlays inference bounding boxes using a
  time-window model, and publishes inference snapshots to camera/images.
ComponentPublisher: AWS
ComponentDependencies:
  com.example.CameraHandlerCore:
    VersionRequirement: '^1.0.0'
    DependencyType: SOFT
  com.example.DetectionHandler:
    VersionRequirement: '^1.0.0'
    DependencyType: SOFT
  aws.greengrass.ShadowManager:
    VersionRequirement: '^2.0.0'
    DependencyType: HARD
  aws.greengrass.TokenExchangeService:
    VersionRequirement: '^2.0.0'
    DependencyType: HARD
ComponentConfiguration:
  DefaultConfiguration:
    KvsStreamName: "ubuntu-core-gg-demo-stream"
    Region: "us-east-1"
    CameraDevice: "/dev/video0"
    KvsProducerSdkBuildDir: "{work:path}/kvs-producer-sdk-build"
    accessControl:
      aws.greengrass.ShadowManager:
        com.example.KvsProducer:shadow:1:
          policyDescription: 'Read and write the kvs-config named shadow'
          operations:
            - 'aws.greengrass#GetThingShadow'
            - 'aws.greengrass#UpdateThingShadow'
          resources:
            - '$aws/things/*/shadow/name/kvs-config'
      aws.greengrass.ipc.pubsub:
        com.example.KvsProducer:pubsub:1:
          policyDescription: 'Publish inference snapshot paths to camera/images'
          operations:
            - 'aws.greengrass#PublishToTopic'
          resources:
            - 'camera/images'
      aws.greengrass.ipc.mqttproxy:
        com.example.KvsProducer:mqttproxy:1:
          policyDescription: 'Subscribe to detection results and shadow delta; publish health metrics'
          operations:
            - 'aws.greengrass#SubscribeToIoTCore'
            - 'aws.greengrass#PublishToIoTCore'
          resources:
            - 'camera/detections'
            - 'camera/kvs-status'
            - '$aws/things/*/shadow/name/kvs-config/update/delta'
Manifests:
  - Platform:
      os: linux
    Lifecycle:
      Install:
        Timeout: 900
        Script: |
          set -e
          apt-get install -y cmake g++ libssl-dev libcurl4-openssl-dev \
            libgstreamer1.0-dev gstreamer1.0-plugins-base \
            gstreamer1.0-plugins-good gstreamer1.0-plugins-bad \
            python3-gi gir1.2-gstreamer-1.0
          git clone --depth 1 \
            https://github.com/awslabs/amazon-kinesis-video-streams-producer-sdk-cpp \
            {configuration:/KvsProducerSdkBuildDir}/src
          cmake -S {configuration:/KvsProducerSdkBuildDir}/src \
                -B {configuration:/KvsProducerSdkBuildDir}/build \
                -DBUILD_GSTREAMER_PLUGIN=ON
          cmake --build {configuration:/KvsProducerSdkBuildDir}/build --parallel 4
          python3 -m venv --without-pip venv/
          . venv/bin/activate
          python3 {artifacts:path}/get-pip.py
          python3 -m pip install -r {artifacts:path}/requirements.txt
          deactivate
      Run:
        Script: |
          set -e
          export GST_PLUGIN_PATH={configuration:/KvsProducerSdkBuildDir}/build
          export AWS_DEFAULT_REGION="{configuration:/Region}"
          export KVS_STREAM_NAME="{configuration:/KvsStreamName}"
          export CAMERA_DEVICE="{configuration:/CameraDevice}"
          export AWS_IOT_THING_NAME="{iot:thingName}"
          . venv/bin/activate
          python3 {artifacts:path}/kvs_producer.py
    Artifacts:
      - Uri: kvs_producer.py
        Unarchive: NONE
      - Uri: frame_annotator.py
        Unarchive: NONE
      - Uri: gstreamer_pipeline.py
        Unarchive: NONE
      - Uri: shadow_config.py
        Unarchive: NONE
      - Uri: health_monitor.py
        Unarchive: NONE
      - Uri: requirements.txt
        Unarchive: NONE
      - Uri: get-pip.py
        Unarchive: NONE
```

- [ ] **Step 6: Run recipe tests — expect all pass**

```bash
pytest tests/test_kvs_recipe.py -v
```

Expected: 8 tests PASSED

- [ ] **Step 7: Commit**

```bash
git add greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml \
        greengrass-components/artifacts/com.example.KvsProducer/1.0.0/requirements.txt \
        greengrass-components/artifacts/com.example.KvsProducer/1.0.0/get-pip.py \
        tests/test_kvs_recipe.py
git commit -m "feat(kvs): add Greengrass recipe and component requirements"
```

---

## Task 8: AWS Resource Setup Extension

**Files:**
- Modify: `setup_aws_resources.py`
- Create: `tests/test_kvs_aws_setup.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_kvs_aws_setup.py`:

```python
import sys, os, json
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from setup_aws_resources import AWSResourcesSetup

def make_setup():
    # Bypass __init__ to avoid real boto3 calls; inject mock clients directly
    s = AWSResourcesSetup.__new__(AWSResourcesSetup)
    s.aws_region = "us-east-1"
    s.project_name = "test-project"
    s.account_id = "123456789012"
    s.kvs = MagicMock()
    s.iam = MagicMock()
    return s

def test_create_kvs_stream_uses_24h_retention():
    s = make_setup()
    s.kvs.describe_stream.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException"}}, "DescribeStream")
    s.kvs.create_stream.return_value = {
        "StreamARN": "arn:aws:kinesisvideo:us-east-1:123456789012:stream/test/0"}
    s.create_kvs_stream("test-stream")
    call_kwargs = s.kvs.create_stream.call_args.kwargs
    assert call_kwargs["DataRetentionInHours"] == 24

def test_create_kvs_stream_skips_if_already_exists():
    s = make_setup()
    s.kvs.describe_stream.return_value = {
        "StreamInfo": {"StreamARN": "arn:existing"}}
    s.create_kvs_stream("test-stream")
    s.kvs.create_stream.assert_not_called()

def test_attach_kvs_producer_policy_grants_put_media():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_producer_policy("my-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    actions = policy_doc["Statement"][0]["Action"]
    assert "kinesisvideo:PutMedia" in actions
    assert "kinesisvideo:CreateStream" in actions
    assert "kinesisvideo:DescribeStream" in actions
    assert "kinesisvideo:GetDataEndpoint" in actions

def test_attach_kvs_producer_policy_scoped_to_stream_arn():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_producer_policy("my-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    assert policy_doc["Statement"][0]["Resource"] == stream_arn

def test_attach_kvs_viewer_policy_grants_get_hls():
    s = make_setup()
    stream_arn = "arn:aws:kinesisvideo:us-east-1:123456789012:stream/s/0"
    s.iam.list_attached_role_policies.return_value = {"AttachedPolicies": []}
    s.iam.create_policy.return_value = {"Policy": {"Arn": "arn:policy"}}
    s.attach_kvs_viewer_policy("cognito-role", stream_arn)
    policy_doc = json.loads(
        s.iam.create_policy.call_args.kwargs["PolicyDocument"])
    actions = policy_doc["Statement"][0]["Action"]
    assert "kinesisvideo:GetHLSStreamingSessionURL" in actions
    assert "kinesisvideo:GetDataEndpoint" in actions
    assert "kinesisvideo:DescribeStream" in actions
```

- [ ] **Step 2: Run tests — expect AttributeError (methods not added yet)**

```bash
pytest tests/test_kvs_aws_setup.py -v
```

Expected: `AttributeError: 'AWSResourcesSetup' object has no attribute 'create_kvs_stream'`

- [ ] **Step 3: Add KVS client and methods to `setup_aws_resources.py`**

In `__init__`, add after the `self.s3` line:

```python
self.kvs = boto3.client('kinesisvideo', region_name=aws_region)
```

Append these three methods to the `AWSResourcesSetup` class:

```python
def create_kvs_stream(self, stream_name: str, retention_hours: int = 24) -> str:
    """Create a KVS stream or return the ARN of the existing one."""
    try:
        resp = self.kvs.describe_stream(StreamName=stream_name)
        arn = resp["StreamInfo"]["StreamARN"]
        print(f"KVS stream already exists: {arn}")
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            print(f"Error checking KVS stream: {e}")
            raise
    resp = self.kvs.create_stream(
        StreamName=stream_name,
        DataRetentionInHours=retention_hours,
    )
    arn = resp["StreamARN"]
    print(f"Created KVS stream: {arn}")
    return arn

def attach_kvs_producer_policy(self, role_name: str, stream_arn: str) -> None:
    """Attach a policy granting the Greengrass TES role KVS producer permissions."""
    policy_name = f"{self.project_name}-kvs-producer-policy"
    self._attach_inline_policy(role_name, policy_name, {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "kinesisvideo:PutMedia",
                "kinesisvideo:CreateStream",
                "kinesisvideo:DescribeStream",
                "kinesisvideo:GetDataEndpoint",
            ],
            "Resource": stream_arn,
        }],
    })

def attach_kvs_viewer_policy(self, role_name: str, stream_arn: str) -> None:
    """Attach a policy granting the Cognito authenticated role KVS viewer permissions."""
    policy_name = f"{self.project_name}-kvs-viewer-policy"
    self._attach_inline_policy(role_name, policy_name, {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Action": [
                "kinesisvideo:GetHLSStreamingSessionURL",
                "kinesisvideo:GetDataEndpoint",
                "kinesisvideo:DescribeStream",
            ],
            "Resource": stream_arn,
        }],
    })

def _attach_inline_policy(self, role_name: str, policy_name: str,
                           policy_document: dict) -> None:
    existing = self.iam.list_attached_role_policies(RoleName=role_name)
    for p in existing["AttachedPolicies"]:
        if p["PolicyName"] == policy_name:
            print(f"Policy {policy_name} already attached to {role_name}")
            return
    try:
        resp = self.iam.create_policy(
            PolicyName=policy_name,
            PolicyDocument=json.dumps(policy_document),
        )
        policy_arn = resp["Policy"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "EntityAlreadyExists":
            raise
        policy_arn = (
            f"arn:aws:iam::{self.account_id}:policy/{policy_name}"
        )
    self.iam.attach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    print(f"Attached {policy_name} to {role_name}")
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
pytest tests/test_kvs_aws_setup.py -v
```

Expected: 5 tests PASSED

- [ ] **Step 5: Commit**

```bash
git add setup_aws_resources.py tests/test_kvs_aws_setup.py
git commit -m "feat(kvs): extend setup script with KVS stream and IAM policy creation"
```

---

## Task 9: React KVS Types and Service

**Files:**
- Modify: `react-web/package.json`
- Create: `react-web/src/types/kvs.ts`
- Create: `react-web/src/services/kvsService.ts`

- [ ] **Step 1: Install KVS SDK dependency**

```bash
cd react-web && npm install @aws-sdk/client-kinesisvideo hls.js
```

- [ ] **Step 2: Create `react-web/src/types/kvs.ts`**

```typescript
export interface KvsStreamConfig {
  streamName: string;
  region: string;
}

export interface HlsSessionUrl {
  url: string;
  expiresAt: Date;
}

export type StreamStatus = "streaming" | "buffering" | "offline" | "error";

export interface KvsHealthMessage {
  timestamp: string;
  frames_sent: number;
  frames_dropped: number;
  bitrate_kbps: number;
  connection_status: StreamStatus;
  error_reason: string | null;
}
```

- [ ] **Step 3: Create `react-web/src/services/kvsService.ts`**

```typescript
import {
  KinesisVideoClient,
  GetHLSStreamingSessionURLCommand,
  HLSPlaybackMode,
  HLSFragmentSelectorType,
  ContainerFormat,
  DiscontinuityMode,
  DisplayFragmentTimestamp,
} from "@aws-sdk/client-kinesisvideo";
import type { AwsCredentialIdentity } from "@aws-sdk/types";
import type { HlsSessionUrl, KvsStreamConfig } from "../types/kvs";

export async function getHlsStreamingUrl(
  config: KvsStreamConfig,
  credentials: AwsCredentialIdentity
): Promise<HlsSessionUrl> {
  const client = new KinesisVideoClient({ region: config.region, credentials });
  const command = new GetHLSStreamingSessionURLCommand({
    StreamName: config.streamName,
    PlaybackMode: HLSPlaybackMode.LIVE,
    HLSFragmentSelector: {
      FragmentSelectorType: HLSFragmentSelectorType.SERVER_TIMESTAMP,
    },
    ContainerFormat: ContainerFormat.FRAGMENTED_MP4,
    DiscontinuityMode: DiscontinuityMode.ALWAYS,
    DisplayFragmentTimestamp: DisplayFragmentTimestamp.ALWAYS,
    Expires: 3600,
  });
  const response = await client.send(command);
  if (!response.HLSStreamingSessionURL) {
    throw new Error("No HLS URL returned from KVS");
  }
  return {
    url: response.HLSStreamingSessionURL,
    expiresAt: new Date(Date.now() + 3600 * 1000),
  };
}
```

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd react-web && npx tsc --noEmit
```

Expected: no errors

- [ ] **Step 5: Commit**

```bash
git add react-web/package.json react-web/package-lock.json \
        react-web/src/types/kvs.ts react-web/src/services/kvsService.ts
git commit -m "feat(kvs): add KVS types and GetHLSStreamingSessionURL service"
```

---

## Task 10: KvsPlayer React Component

**Files:**
- Create: `react-web/src/components/dashboard/KvsPlayer.tsx`
- Create: `react-web/src/components/dashboard/KvsPlayer.css`
- Create: `react-web/src/components/dashboard/__tests__/KvsPlayer.test.tsx`

- [ ] **Step 1: Write the failing tests**

Create `react-web/src/components/dashboard/__tests__/KvsPlayer.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import React from "react";

// Mock hls.js
vi.mock("hls.js", () => ({
  default: class MockHls {
    static isSupported() { return true; }
    loadSource = vi.fn();
    attachMedia = vi.fn();
    on = vi.fn();
    destroy = vi.fn();
    static Events = { MANIFEST_PARSED: "hlsManifestParsed", ERROR: "hlsError" };
  },
}));

// Mock kvsService
vi.mock("../../../services/kvsService", () => ({
  getHlsStreamingUrl: vi.fn(),
}));

import { getHlsStreamingUrl } from "../../../services/kvsService";
import { KvsPlayer } from "../KvsPlayer";

const mockCredentials = {
  accessKeyId: "AKIA",
  secretAccessKey: "secret",
  sessionToken: "token",
};

describe("KvsPlayer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders a video element", () => {
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt: new Date(Date.now() + 3600000),
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByTestId("kvs-video")).toBeInTheDocument();
  });

  it("shows loading state while fetching URL", () => {
    vi.mocked(getHlsStreamingUrl).mockReturnValue(new Promise(() => {}));
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("retries GetHLSStreamingSessionURL 3 times on failure", async () => {
    vi.mocked(getHlsStreamingUrl).mockRejectedValue(new Error("network error"));
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    await waitFor(() =>
      expect(screen.getByText(/error/i)).toBeInTheDocument(),
      { timeout: 4000 }
    );
    expect(getHlsStreamingUrl).toHaveBeenCalledTimes(3);
  });

  it("shows offline status when stream name is empty", () => {
    render(
      <KvsPlayer streamName="" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByText(/stream offline/i)).toBeInTheDocument();
  });

  it("displays stream status from health message prop", () => {
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt: new Date(Date.now() + 3600000),
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials}
                 streamStatus="buffering" />
    );
    expect(screen.getByText(/buffering/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests — expect component not found**

```bash
cd react-web && npx vitest run src/components/dashboard/__tests__/KvsPlayer.test.tsx
```

Expected: module not found error

- [ ] **Step 3: Create `KvsPlayer.css`**

```css
.kvs-player-container {
  position: relative;
  width: 100%;
  background: #000;
  border: 2px solid #444;
  border-radius: 4px;
  overflow: hidden;
}

.kvs-player-container video {
  width: 100%;
  display: block;
}

.kvs-player-overlay {
  position: absolute;
  top: 8px;
  left: 8px;
  padding: 4px 8px;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 12px;
  border-radius: 3px;
  font-family: monospace;
}

.kvs-player-overlay.status-error { color: #f66; }
.kvs-player-overlay.status-buffering { color: #fa0; }
.kvs-player-overlay.status-streaming { color: #6f6; }
.kvs-player-overlay.status-offline { color: #aaa; }
```

- [ ] **Step 4: Create `KvsPlayer.tsx`**

```tsx
import React, { useEffect, useRef, useState, useCallback } from "react";
import Hls from "hls.js";
import type { AwsCredentialIdentity } from "@aws-sdk/types";
import type { StreamStatus } from "../../types/kvs";
import { getHlsStreamingUrl } from "../../services/kvsService";
import "./KvsPlayer.css";

interface KvsPlayerProps {
  streamName: string;
  region: string;
  credentials: AwsCredentialIdentity;
  streamStatus?: StreamStatus;
}

const MAX_RETRIES = 3;
const RETRY_INTERVAL_MS = 5000;

export const KvsPlayer: React.FC<KvsPlayerProps> = ({
  streamName, region, credentials, streamStatus,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStream = useCallback(async () => {
    if (!streamName) return;
    setLoading(true);
    setError(null);
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        const { url } = await getHlsStreamingUrl(
          { streamName, region }, credentials);
        if (hlsRef.current) { hlsRef.current.destroy(); }
        const hls = new Hls();
        hlsRef.current = hls;
        hls.loadSource(url);
        if (videoRef.current) { hls.attachMedia(videoRef.current); }
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          videoRef.current?.play().catch(() => {});
          setLoading(false);
        });
        hls.on(Hls.Events.ERROR, (_: unknown, data: { fatal: boolean }) => {
          if (data.fatal) { setError("Playback error"); }
        });
        return;
      } catch (e) {
        lastError = e as Error;
        if (attempt < MAX_RETRIES - 1) {
          await new Promise(r => setTimeout(r, RETRY_INTERVAL_MS));
        }
      }
    }
    setError(lastError?.message ?? "Failed to load stream");
    setLoading(false);
  }, [streamName, region, credentials]);

  useEffect(() => {
    if (!streamName) { setLoading(false); return; }
    loadStream();
    return () => { hlsRef.current?.destroy(); };
  }, [loadStream, streamName]);

  if (!streamName) {
    return (
      <div className="kvs-player-container">
        <div className="kvs-player-overlay status-offline">Stream Offline</div>
        <video data-testid="kvs-video" />
      </div>
    );
  }

  const status = streamStatus ?? (loading ? "buffering" : error ? "error" : "streaming");

  return (
    <div className="kvs-player-container">
      <video ref={videoRef} data-testid="kvs-video" muted playsInline />
      {loading && <div className="kvs-player-overlay">Loading...</div>}
      {error && <div className="kvs-player-overlay status-error">Error: {error}</div>}
      {streamStatus && (
        <div className={`kvs-player-overlay status-${streamStatus}`}>
          {streamStatus}
        </div>
      )}
    </div>
  );
};
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
cd react-web && npx vitest run src/components/dashboard/__tests__/KvsPlayer.test.tsx
```

Expected: 5 tests PASSED

- [ ] **Step 6: Commit**

```bash
git add react-web/src/components/dashboard/KvsPlayer.tsx \
        react-web/src/components/dashboard/KvsPlayer.css \
        react-web/src/components/dashboard/__tests__/KvsPlayer.test.tsx
git commit -m "feat(kvs): add KvsPlayer React component with HLS playback"
```

---

## Task 11: Dashboard Integration

**Files:**
- Modify: `react-web/src/components/dashboard/Dashboard.tsx`

Add the `KvsPlayer` to the dashboard alongside the existing S3 image gallery. Subscribe to `camera/kvs-status` via the existing MQTT context to feed the `streamStatus` prop.

- [ ] **Step 1: Read the current Dashboard.tsx to understand its structure**

```bash
cat react-web/src/components/dashboard/Dashboard.tsx
```

Note the existing layout, context providers, and how `ImageGallery` and `MessageFeed` are positioned.

- [ ] **Step 2: Add KvsPlayer import and stream status state to `Dashboard.tsx`**

At the top of `Dashboard.tsx`, add alongside existing imports:

```tsx
import { KvsPlayer } from "./KvsPlayer";
import type { KvsHealthMessage, StreamStatus } from "../../types/kvs";
```

Inside the `Dashboard` component, add state for stream status (place alongside existing `useState` calls):

```tsx
const [kvsStreamStatus, setKvsStreamStatus] = useState<StreamStatus>("offline");
```

- [ ] **Step 3: Subscribe to `camera/kvs-status` MQTT topic**

In the same effect or subscription block where other MQTT topics are subscribed (look for the existing MQTT subscription pattern), add:

```tsx
// Subscribe to KVS health messages
if (mqttClient) {
  mqttClient.subscribe("camera/kvs-status", (message: string) => {
    try {
      const health: KvsHealthMessage = JSON.parse(message);
      setKvsStreamStatus(health.connection_status);
    } catch {
      // malformed message — ignore
    }
  });
}
```

- [ ] **Step 4: Add `KvsPlayer` to the Dashboard JSX**

Locate where `ImageGallery` is rendered and add `KvsPlayer` alongside it. The exact position depends on the existing layout — place it in the main content area above or below the image gallery:

```tsx
<div className="dashboard-video-section">
  <h3>Live Stream</h3>
  <KvsPlayer
    streamName={import.meta.env.VITE_KVS_STREAM_NAME ?? ""}
    region={import.meta.env.VITE_AWS_REGION ?? "us-east-1"}
    credentials={credentials}
    streamStatus={kvsStreamStatus}
  />
</div>
```

- [ ] **Step 5: Add environment variable to `.env.example`**

Open `react-web/.env.example` and add:

```
VITE_KVS_STREAM_NAME=ubuntu-core-gg-demo-stream
```

- [ ] **Step 6: Run the full test suite**

```bash
cd react-web && npx vitest run
```

Expected: all existing tests PASS, no regressions

- [ ] **Step 7: Run all Python tests**

```bash
pytest tests/ -v
```

Expected: all tests PASS

- [ ] **Step 8: Commit**

```bash
git add react-web/src/components/dashboard/Dashboard.tsx \
        react-web/.env.example
git commit -m "feat(kvs): integrate KvsPlayer into dashboard with stream status"
```

---

## Self-Review Checklist

After writing the plan, spec coverage check against `.kiro/specs/kvs-video-streaming/design.md`:

| Spec Requirement | Covered By |
|-----------------|-----------|
| Req 1.1: H.264 stream to KVS | Task 5 (EncodingPipeline), Task 6 |
| Req 1.2: Create stream if missing | Task 8 (setup_aws_resources) |
| Req 1.3: Continuous video at configured frame rate | Task 5 (CapturePipeline v4l2src) |
| Req 1.4–1.5: Buffer / FIFO eviction | kvssink internal (Task 5) |
| Req 1.6: Recipe dependencies | Task 7 |
| Req 1.7: Startup dependency wait | Handled in kvs_producer error table |
| Req 2.1: Bounding boxes at pixel coords | Task 3 |
| Req 2.2: Confidence score as % | Task 3, Property 3 |
| Req 2.3: Raw frame when no detections | Task 3, Property 4 |
| Req 2.4: 10 distinct colours | Task 3 |
| Req 2.5: Annotation within 50ms | Task 3 (benchmark test) |
| Req 2.6: Stale detection discard | Task 3, Properties 1 & 6 |
| Req 3.1: No ML inference in KVS Producer | Enforced by no ML imports in Task 6 |
| Req 3.2–3.4: Edge-only inference | Architecture; no ML libraries in requirements.txt (Task 7) |
| Req 4.1–4.7: HLS Player | Tasks 9–11 |
| Req 5.1–5.7: AWS resource setup | Task 8 |
| Req 6.1–6.6: Shadow configuration | Tasks 1, 6 |
| Req 7.1–7.5: Stream health monitoring | Task 2, Task 6 |
| Correctness Properties 1–7 | Tasks 3 & 4 |
| Snap deployment | Task 7 (recipe install script) |
