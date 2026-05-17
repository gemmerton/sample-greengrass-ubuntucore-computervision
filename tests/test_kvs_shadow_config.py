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

def test_apply_delta_partial_preserves_current_config_fields():
    # AWS shadow deltas only carry changed fields; unchanged fields must not
    # revert to DEFAULT_CONFIG values — they must be taken from current_config.
    mgr = ShadowConfigManager(MagicMock(), "t")
    current = KvsConfig(
        stream_name="my-stream",
        frame_rate=25,
        resolution="1280x720",
        streaming_enabled=False,
        staleness_window_seconds=60.0,
        snapshot_interval_seconds=5,
    )
    new_config, errors = mgr.apply_delta({"resolution": "1920x1080"}, current)
    assert errors == []
    assert new_config.resolution == "1920x1080"
    assert new_config.frame_rate == 25          # must come from current, not DEFAULT (15)
    assert new_config.streaming_enabled is False # must come from current, not DEFAULT (True)
    assert new_config.stream_name == "my-stream"
    assert new_config.staleness_window_seconds == 60.0
    assert new_config.snapshot_interval_seconds == 5

def test_report_state_puts_streaming_status_in_payload():
    ipc = MagicMock()
    mgr = ShadowConfigManager(ipc, "my-thing")
    mgr.report_state(KvsConfig("s", 15, "640x480", True, 30.0, 10), "streaming")
    ipc.update_thing_shadow.assert_called_once()
    kw = ipc.update_thing_shadow.call_args.kwargs
    payload = json.loads(kw["payload"])
    assert payload["state"]["reported"]["streaming_status"] == "streaming"
