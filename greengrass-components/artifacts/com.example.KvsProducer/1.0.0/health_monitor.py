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
