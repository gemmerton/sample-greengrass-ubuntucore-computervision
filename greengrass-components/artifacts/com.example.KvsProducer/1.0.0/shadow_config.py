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
