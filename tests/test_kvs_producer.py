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
    p._config = type(p._config)(**{**p._config.__dict__, 'streaming_enabled': False})
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
