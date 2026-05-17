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
            f"! video/x-raw,framerate=1/{self._snapshot_interval} ! jpegenc "
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
        try:
            buf = Gst.Buffer.new_wrapped(frame.tobytes())
            flow = self._appsrc.emit("push-buffer", buf)
            if flow != Gst.FlowReturn.OK:
                logger.warning("push-buffer returned %s", flow)
                return False
            return True
        except Exception as e:
            logger.warning("push_frame failed: %s", e)
            return False

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
