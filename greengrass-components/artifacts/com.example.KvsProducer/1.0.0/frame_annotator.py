from dataclasses import dataclass
from typing import Optional
import cv2, logging, numpy as np, threading

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
    def __init__(self, staleness_window_seconds: float = 30.0):
        self._staleness_window = staleness_window_seconds
        self._detections: list = []
        self._received_at: Optional[float] = None
        self._label_colour_map: dict = {}
        self._colour_index = 0
        self._lock = threading.Lock()

    def update_detections(self, detections: list, received_at: float) -> None:
        with self._lock:
            self._detections = detections
            self._received_at = received_at

    def annotate(self, frame: np.ndarray, frame_time: float) -> np.ndarray:
        result = frame.copy()
        with self._lock:
            received_at = self._received_at
            detections = list(self._detections)
        if (received_at is None
                or frame_time - received_at > self._staleness_window):
            return result
        for d in detections:
            colour = self.get_colour(d.label)
            x1, y1 = int(d.box.xmin), int(d.box.ymin)
            x2, y2 = int(d.box.xmax), int(d.box.ymax)
            cv2.rectangle(result, (x1, y1), (x2, y2), colour, 2)
            label_text = f"{d.label} {d.score * 100:.1f}%"
            cv2.putText(result, label_text, (x1, max(0, y1 - 5)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1)
        return result

    def get_colour(self, class_label: str) -> tuple:
        with self._lock:
            if class_label not in self._label_colour_map:
                self._label_colour_map[class_label] = (
                    COLOUR_PALETTE[self._colour_index % len(COLOUR_PALETTE)]
                )
                self._colour_index += 1
            return self._label_colour_map[class_label]
