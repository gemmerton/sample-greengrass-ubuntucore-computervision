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
