import sys, os, importlib
from unittest.mock import MagicMock, patch, call
import numpy as np

# Mock gi BEFORE importing gstreamer_pipeline.
# Force-remove any stale cached version of gstreamer_pipeline first so that
# whichever test file pytest collects first (test_kvs_producer.py imports the
# module via kvs_producer.py with its own gi mock) does not pollute the Gst
# binding seen by the tests in this file.
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

# Remove any stale cache entry so gstreamer_pipeline is re-imported with the
# gi mock defined above, regardless of test collection order.
sys.modules.pop("gstreamer_pipeline", None)

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
    # Stop then start again — check that set_state was called with NULL
    calls = mock_pipeline.set_state.call_args_list
    assert any(c[0][0] == gst_mock.State.NULL for c in calls), \
        f"Expected State.NULL in calls, got {calls}"
    assert p._framerate == 10
    assert p._width == 1280
    assert p._height == 720


def test_capture_pipeline_pop_error_returns_none_before_start():
    p = CapturePipeline("/dev/video0", 15, 640, 480, 10)
    assert p.pop_error() is None


def test_encoding_pipeline_pop_error_returns_none_when_no_error():
    p = EncodingPipeline("s", "us-east-1", 15, 640, 480)
    p.start()
    mock_pipeline = gst_mock.parse_launch.return_value
    mock_pipeline.get_bus.return_value.timed_pop_filtered.return_value = None
    assert p.pop_error() is None


def test_encoding_pipeline_pop_error_returns_message_string_on_error():
    p = EncodingPipeline("s", "us-east-1", 15, 640, 480)
    p.start()
    mock_pipeline = gst_mock.parse_launch.return_value
    mock_err = MagicMock()
    mock_err.message = "KVS credential error"
    mock_msg = MagicMock()
    mock_msg.parse_error.return_value = (mock_err, "debug details")
    mock_pipeline.get_bus.return_value.timed_pop_filtered.return_value = mock_msg
    result = p.pop_error()
    assert result is not None
    assert "KVS credential error" in result
