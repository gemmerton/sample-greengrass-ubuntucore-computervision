from dataclasses import dataclass, replace
import json
import logging

logger = logging.getLogger(__name__)

VALID_RESOLUTIONS = {"640x480", "1280x720", "1920x1080"}

@dataclass(frozen=True)
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
            return replace(DEFAULT_CONFIG)

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

        stream_name = data.get("stream_name", DEFAULT_CONFIG.stream_name)

        fr = data.get("frame_rate")
        if fr is not None and not (isinstance(fr, int) and 1 <= fr <= 30):
            errors.append(f"frame_rate {fr!r} must be integer in [1, 30]")
        frame_rate = fr if (fr is not None and isinstance(fr, int) and 1 <= fr <= 30) else DEFAULT_CONFIG.frame_rate

        res = data.get("resolution")
        if res is not None and res not in VALID_RESOLUTIONS:
            errors.append(f"resolution {res!r} must be one of {VALID_RESOLUTIONS}")
        resolution = res if (res is not None and res in VALID_RESOLUTIONS) else DEFAULT_CONFIG.resolution

        se = data.get("streaming_enabled")
        if se is not None and not isinstance(se, bool):
            errors.append(f"streaming_enabled {se!r} must be a boolean")
        streaming_enabled = se if (se is not None and isinstance(se, bool)) else DEFAULT_CONFIG.streaming_enabled

        sw = data.get("staleness_window_seconds")
        if sw is not None and not (isinstance(sw, (int, float)) and sw > 0):
            errors.append(f"staleness_window_seconds {sw!r} must be float > 0")
        staleness_window_seconds = float(sw) if (sw is not None and isinstance(sw, (int, float)) and sw > 0) else DEFAULT_CONFIG.staleness_window_seconds

        si = data.get("snapshot_interval_seconds")
        if si is not None and not (isinstance(si, int) and 1 <= si <= 3600):
            errors.append(f"snapshot_interval_seconds {si!r} must be integer in [1, 3600]")
        snapshot_interval_seconds = si if (si is not None and isinstance(si, int) and 1 <= si <= 3600) else DEFAULT_CONFIG.snapshot_interval_seconds

        config = KvsConfig(
            stream_name=stream_name,
            frame_rate=frame_rate,
            resolution=resolution,
            streaming_enabled=streaming_enabled,
            staleness_window_seconds=staleness_window_seconds,
            snapshot_interval_seconds=snapshot_interval_seconds,
        )
        return config, errors
