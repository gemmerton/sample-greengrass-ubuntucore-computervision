import os, sys, json, time, logging, datetime
from dataclasses import replace
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
        self._capture_pipeline = None
        self._encoding_pipeline = None
        self._last_frame_sent_time: float = 0.0
        self._last_health_publish: float = 0.0

    def run(self):
        self._config = self._shadow_mgr.read_config()
        if self._stream_name:
            self._config = replace(self._config, stream_name=self._stream_name)
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
