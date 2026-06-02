"""InferenceHandler - Unified shadow-reactive inference for edge computer vision.

Captures frames from the camera at a configurable interval, reads active model
metadata from the model-config cloud shadow, calls OVMS gRPC for inference,
and publishes results to camera/inference via IoT Core MQTT.
"""

import os
import sys
import time
import json
import logging
import traceback

import cv2
import numpy as np
from ovmsclient import make_grpc_client
import awsiot.greengrasscoreipc.clientv2 as clientv2

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'shared'))
from cloud_shadow import CloudShadowClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"


class InferenceHandler:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.camera_device = os.environ.get("CAMERA_DEVICE", "/dev/video1")
        self.ovms_url = os.environ.get("OVMS_GRPC_URL", "localhost:9000")
        self.inference_interval = float(os.environ.get("INFERENCE_INTERVAL", "1.0"))
        self.confidence_threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))
        self.pub_topic = os.environ.get("PUB_TOPIC", "camera/inference")

        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.shadow_client = CloudShadowClient(self.thing_name, SHADOW_NAME)
        self.model_metadata = None
        self.active_model_id = None
        self.labels = {}  # class_id -> label string, loaded from model's labels.txt

        logger.info(
            "InferenceHandler initialized: thing=%s camera=%s ovms=%s interval=%ss",
            self.thing_name, self.camera_device, self.ovms_url, self.inference_interval,
        )

    def run(self):
        self._subscribe_to_shadow_delta()
        self._load_active_model()

        while True:
            if self.model_metadata is None:
                logger.info("No active model, waiting...")
                time.sleep(5)
                self._load_active_model()
                continue

            try:
                self._capture_and_infer()
            except Exception as e:
                logger.error("Inference cycle failed: %s", e)
                traceback.print_exc()

            time.sleep(self.inference_interval)

    def _subscribe_to_shadow_delta(self):
        if not self.thing_name:
            return
        delta_topic = f"$aws/things/{self.thing_name}/shadow/name/{SHADOW_NAME}/update/delta"
        self.ipc_client.subscribe_to_iot_core(
            topic_name=delta_topic,
            qos="1",
            on_stream_event=self._on_shadow_delta,
            on_stream_error=lambda e: logger.error("Delta stream error: %s", e),
            on_stream_closed=lambda: logger.warning("Delta stream closed"),
        )
        logger.info("Subscribed to shadow delta: %s", delta_topic)

    def _on_shadow_delta(self, event):
        try:
            payload = json.loads(event.message.payload)
            state = payload.get("state", {})
            if "active_model" in state:
                new_model = state["active_model"]
                logger.info("Shadow delta: active_model changed to '%s'", new_model)
                self._switch_to_model(new_model)
            if "confidence_threshold" in state:
                self.confidence_threshold = float(state["confidence_threshold"])
                logger.info("Confidence threshold updated to %s", self.confidence_threshold)
                self.shadow_client.update_reported({"confidence_threshold": self.confidence_threshold})
            if "inference_interval" in state:
                self.inference_interval = float(state["inference_interval"])
                logger.info("Inference interval updated to %ss", self.inference_interval)
                self.shadow_client.update_reported({"inference_interval": self.inference_interval})
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _switch_to_model(self, model_id):
        """Handle an explicit model switch request from shadow delta.

        Reads model metadata from reported state, switches, reports back.
        """
        if not self.thing_name or not model_id:
            return
        if model_id == self.active_model_id:
            self._report_and_clear_desired()
            return
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        models = reported.get("models", {})
        if model_id not in models:
            logger.warning("Model '%s' not in reported models, cannot switch", model_id)
            return
        entry = models[model_id]
        if entry.get("status") != "ready":
            logger.warning("Model '%s' not ready (status=%s), cannot switch", model_id, entry.get("status"))
            return
        metadata = entry.get("model_metadata", {})
        logger.info("Active model changed: %s -> %s", self.active_model_id, model_id)
        self.active_model_id = model_id
        self.model_metadata = metadata
        self._load_labels()
        self._report_and_clear_desired()

    def _report_and_clear_desired(self):
        """Report active_model to cloud shadow reported state.

        Only updates reported.active_model. Does NOT clear desired — once
        reported matches desired, the delta resolves naturally.
        """
        if not self.thing_name or not self.active_model_id:
            return
        if self.shadow_client.update_reported({"active_model": self.active_model_id}):
            logger.info("Reported active_model=%s", self.active_model_id)
        else:
            logger.warning("Failed to report active_model=%s", self.active_model_id)

    def _load_active_model(self):
        """Determine which model to use on startup or when polling.

        Priority:
        1. desired.active_model (user explicitly requested via UI)
        2. reported.active_model (persisted from previous run, survives restarts)
        3. First ready model (cold start, nothing ever set)

        Only reports back to shadow if the active model actually changes.
        """
        if not self.thing_name:
            return
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        desired = shadow.get("state", {}).get("desired", {})

        # Restore confidence_threshold and inference_interval from shadow
        if "confidence_threshold" in reported:
            self.confidence_threshold = float(reported["confidence_threshold"])
        if "inference_interval" in reported:
            self.inference_interval = float(reported["inference_interval"])
        logger.info("Inference interval updated to %ss", self.inference_interval)

        models = reported.get("models", {})
        if not models:
            logger.info("No models in reported state")
            self.model_metadata = None
            self.active_model_id = None
            return

        # Determine target model using priority chain
        target_model_id = None

        # Priority 1: desired.active_model (explicit user request)
        desired_model = desired.get("active_model")
        if desired_model and desired_model in models:
            target_model_id = desired_model

        # Priority 2: reported.active_model (persisted truth from last run)
        if not target_model_id:
            reported_model = reported.get("active_model")
            if reported_model and reported_model in models:
                target_model_id = reported_model

        # Priority 3: first ready model (cold start)
        if not target_model_id:
            target_model_id = next(
                (mid for mid, m in models.items() if m.get("status") == "ready"),
                None,
            )

        if not target_model_id:
            self.model_metadata = None
            self.active_model_id = None
            return

        entry = models[target_model_id]
        if entry.get("status") != "ready":
            logger.info("Model '%s' not ready (status=%s)", target_model_id, entry.get("status"))
            self.model_metadata = None
            self.active_model_id = None
            return

        metadata = entry.get("model_metadata", {})
        if self.active_model_id != target_model_id:
            logger.info("Active model changed: %s -> %s", self.active_model_id, target_model_id)
            self.active_model_id = target_model_id
            self.model_metadata = metadata
            self._load_labels()
            logger.info("Model metadata: %s", json.dumps(metadata, indent=2))
            self._report_active_model()
        elif self.model_metadata is None:
            self.model_metadata = metadata
            self._load_labels()

    def _report_active_model(self):
        self._report_and_clear_desired()

    def _get_frame(self):
        snapshot_dir = os.environ.get(
            "SNAPSHOT_DIR",
            "/var/snap/aws-iot-greengrass/common/greengrass/v2/work/com.example.KvsProducer/snapshots"
        )
        if not os.path.isdir(snapshot_dir):
            return None
        try:
            import glob as _glob
            snapshots = sorted(_glob.glob(os.path.join(snapshot_dir, "snapshot_*.jpg")))
            if not snapshots:
                return None
            latest = snapshots[-1]
            mtime = os.path.getmtime(latest)
            if time.time() - mtime > 10:
                return None
            frame = cv2.imread(latest)
            return frame
        except Exception:
            return None

    def _capture_and_infer(self):
        frame = self._get_frame()
        if frame is None:
            return

        frame_height, frame_width = frame.shape[:2]

        model_name = self.model_metadata.get("model_name", "")
        input_name = self.model_metadata.get("input_name", "data")
        input_shape = self.model_metadata.get("input_shape", [1, 3, 224, 224])
        output_names = self.model_metadata.get("output_names", [])

        preprocessed = self._preprocess(frame, input_shape)

        start_time = time.time()
        try:
            client = make_grpc_client(self.ovms_url)
            result = client.predict({input_name: preprocessed}, model_name)
        except Exception as e:
            logger.error("OVMS predict failed: %s", e)
            return
        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        result_payload = self._postprocess(
            result, output_names, frame_width, frame_height, inference_time_ms
        )
        if result_payload:
            self._publish(result_payload)

    def _preprocess(self, frame, input_shape):
        dtype_str = self.model_metadata.get("input_dtype", "float32")
        out_dtype = np.uint8 if dtype_str == "uint8" else np.float32
        normalize = self.model_metadata.get("normalize", False)

        if len(input_shape) == 4:
            _, c_or_h, h_or_w, w_or_c = input_shape
            if c_or_h <= 4:
                # NCHW layout
                target_h, target_w = h_or_w, w_or_c
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                transposed = np.transpose(rgb, (2, 0, 1))
                result = np.expand_dims(transposed, axis=0).astype(out_dtype)
                if normalize:
                    result = result / 255.0
                return result
            else:
                # NHWC layout
                target_h, target_w = c_or_h, h_or_w
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                result = np.expand_dims(rgb, axis=0).astype(out_dtype)
                if normalize:
                    result = result / 255.0
                return result
        resized = cv2.resize(frame, (224, 224))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return np.expand_dims(np.transpose(rgb, (2, 0, 1)), axis=0).astype(out_dtype)

    def _load_labels(self):
        """Load labels from the path stored in model metadata."""
        labels_path = self.model_metadata.get("labels_file")
        if not labels_path:
            self.labels = {}
            return

        if not os.path.isfile(labels_path):
            logger.warning("Labels file not found: %s", labels_path)
            self.labels = {}
            return

        try:
            with open(labels_path, "r") as f:
                self.labels = {i: line.strip() for i, line in enumerate(f) if line.strip()}
            logger.info("Loaded %d labels from %s", len(self.labels), labels_path)
        except Exception as e:
            logger.error("Failed to load labels from %s: %s", labels_path, e)
            self.labels = {}

    def _get_label(self, class_id):
        return self.labels.get(class_id, f"class_{class_id}")

    def _postprocess(self, result, output_names, frame_width, frame_height, inference_time_ms):
        result_dict = self._normalize_result(result)

        # Auto-detect output format:
        # Format 1: YOLOv8 single-tensor [1, 84, 8400] (transposed detection grid)
        # Format 2: OpenVINO zoo single-tensor [1,1,N,7] (detection_out)
        # Format 3: TF2 multi-tensor (detection_boxes, detection_scores, detection_classes)
        if self._is_yolov8_output(result_dict):
            return self._postprocess_yolov8(result_dict, frame_width, frame_height, inference_time_ms)
        if self._is_tf2_detection_output(result_dict):
            return self._postprocess_tf2_detection(result_dict, frame_width, frame_height, inference_time_ms)
        if "detection_out" in output_names or self._is_ov_detection_output(result_dict):
            return self._postprocess_ov_detection(result_dict, frame_width, frame_height, inference_time_ms)
        return self._postprocess_classification(result_dict, inference_time_ms)

    @staticmethod
    def _normalize_result(result):
        if isinstance(result, dict):
            return result
        if isinstance(result, np.ndarray):
            return {"output": result}
        return {"output": np.array(result)}

    def _is_ov_detection_output(self, result_dict):
        for val in result_dict.values():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[2] > 1 and val.shape[3] == 7:
                return True
        return False

    @staticmethod
    def _is_tf2_detection_output(result_dict):
        keys = set(result_dict.keys())
        return "detection_boxes" in keys and "detection_scores" in keys and "detection_classes" in keys

    def _is_yolov8_output(self, result_dict):
        """Detect YOLOv8 output: shape [1, num_classes+4, num_detections] where dim1 < dim2."""
        for val in result_dict.values():
            if hasattr(val, 'shape') and len(val.shape) == 3:
                _, dim1, dim2 = val.shape
                if dim1 < dim2 and dim1 >= 5:
                    return True
        return False

    def _postprocess_yolov8(self, result_dict, frame_width, frame_height, inference_time_ms):
        """Parse YOLOv8 output: single tensor [1, 4+num_classes, num_detections]."""
        output = None
        for val in result_dict.values():
            if hasattr(val, 'shape') and len(val.shape) == 3:
                output = val
                break
        if output is None:
            return None

        predictions = np.squeeze(output).T

        boxes_xywh = predictions[:, :4]
        class_scores = predictions[:, 4:]

        max_scores = np.max(class_scores, axis=1)
        class_ids = np.argmax(class_scores, axis=1)

        yolo_threshold = max(self.confidence_threshold, 0.5)
        mask = max_scores > yolo_threshold
        boxes_xywh = boxes_xywh[mask]
        scores = max_scores[mask]
        class_ids = class_ids[mask]

        if len(scores) == 0:
            return None

        input_shape = self.model_metadata.get("input_shape", [1, 3, 640, 640])
        input_h = input_shape[2]
        input_w = input_shape[3]

        boxes_xyxy = np.zeros_like(boxes_xywh)
        boxes_xyxy[:, 0] = (boxes_xywh[:, 0] - boxes_xywh[:, 2] / 2) / input_w
        boxes_xyxy[:, 1] = (boxes_xywh[:, 1] - boxes_xywh[:, 3] / 2) / input_h
        boxes_xyxy[:, 2] = (boxes_xywh[:, 0] + boxes_xywh[:, 2] / 2) / input_w
        boxes_xyxy[:, 3] = (boxes_xywh[:, 1] + boxes_xywh[:, 3] / 2) / input_h

        indices = self._nms(boxes_xyxy, scores, iou_threshold=0.5)
        boxes_xyxy = boxes_xyxy[indices]
        scores = scores[indices]
        class_ids = class_ids[indices]

        max_det = 50
        if len(scores) > max_det:
            top_indices = np.argsort(scores)[::-1][:max_det]
            boxes_xyxy = boxes_xyxy[top_indices]
            scores = scores[top_indices]
            class_ids = class_ids[top_indices]

        detections = []
        for i in range(len(scores)):
            detections.append({
                "label": self._get_label(int(class_ids[i])),
                "score": round(float(scores[i]), 4),
                "box": {
                    "xmin": round(float(np.clip(boxes_xyxy[i, 0], 0, 1)), 4),
                    "ymin": round(float(np.clip(boxes_xyxy[i, 1], 0, 1)), 4),
                    "xmax": round(float(np.clip(boxes_xyxy[i, 2], 0, 1)), 4),
                    "ymax": round(float(np.clip(boxes_xyxy[i, 3], 0, 1)), 4),
                },
            })

        if not detections:
            return None

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "detection",
            "results": {"detections": detections, "count": len(detections)},
            "inference_time_ms": inference_time_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "confidence_threshold": self.confidence_threshold,
        }

    @staticmethod
    def _nms(boxes, scores, iou_threshold=0.5):
        """Non-maximum suppression."""
        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])
            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            iou = inter / (areas[i] + areas[order[1:]] - inter)
            inds = np.where(iou <= iou_threshold)[0]
            order = order[inds + 1]

        return np.array(keep)

    def _postprocess_ov_detection(self, result_dict, frame_width, frame_height, inference_time_ms):
        """Parse OpenVINO zoo format: single tensor with shape [1, 1, N, 7].
        Each row: [image_id, label_id, confidence, xmin, ymin, xmax, ymax]
        """
        output = None
        for val in result_dict.values():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[3] == 7:
                output = val
                break
        if output is None:
            for val in result_dict.values():
                output = val
                break
        if output is None:
            return None

        detections = []
        output = np.squeeze(output)
        for det in output:
            if len(det) < 7:
                continue
            confidence = float(det[2])
            if confidence < self.confidence_threshold:
                continue
            label_id = int(det[1])
            xmin = float(np.clip(det[3], 0, 1))
            ymin = float(np.clip(det[4], 0, 1))
            xmax = float(np.clip(det[5], 0, 1))
            ymax = float(np.clip(det[6], 0, 1))
            detections.append({
                "label": self._get_label(label_id),
                "score": round(confidence, 4),
                "box": {
                    "xmin": round(xmin, 4),
                    "ymin": round(ymin, 4),
                    "xmax": round(xmax, 4),
                    "ymax": round(ymax, 4),
                },
            })

        if not detections:
            return None

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "detection",
            "results": {"detections": detections, "count": len(detections)},
            "inference_time_ms": inference_time_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "confidence_threshold": self.confidence_threshold,
        }

    def _postprocess_tf2_detection(self, result_dict, frame_width, frame_height, inference_time_ms):
        """Parse TF2 model zoo format: separate tensors for boxes, scores, classes.
        detection_boxes: [1, N, 4] normalized (ymin, xmin, ymax, xmax)
        detection_scores: [1, N]
        detection_classes: [1, N]
        """
        boxes = np.squeeze(result_dict["detection_boxes"])
        scores = np.squeeze(result_dict["detection_scores"])
        classes = np.squeeze(result_dict["detection_classes"])

        detections = []
        for i in range(len(scores)):
            confidence = float(scores[i])
            if confidence < self.confidence_threshold:
                continue
            label_id = int(classes[i])
            ymin, xmin, ymax, xmax = boxes[i]
            detections.append({
                "label": self._get_label(label_id),
                "score": round(confidence, 4),
                "box": {
                    "xmin": round(float(np.clip(xmin, 0, 1)), 4),
                    "ymin": round(float(np.clip(ymin, 0, 1)), 4),
                    "xmax": round(float(np.clip(xmax, 0, 1)), 4),
                    "ymax": round(float(np.clip(ymax, 0, 1)), 4),
                },
            })

        if not detections:
            return None

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "detection",
            "results": {"detections": detections, "count": len(detections)},
            "inference_time_ms": inference_time_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "confidence_threshold": self.confidence_threshold,
        }

    def _postprocess_classification(self, result_dict, inference_time_ms):
        output = None
        for key, val in result_dict.items():
            squeezed = np.squeeze(val)
            if squeezed.ndim >= 1 and squeezed.size > 1:
                if output is None or squeezed.size > output.size:
                    output = squeezed
        if output is None or output.ndim == 0:
            return None

        probs = output
        top_k = 5
        top_indices = np.argsort(probs)[::-1][:top_k]
        classifications = []
        for idx in top_indices:
            conf = float(probs[idx])
            if conf < self.confidence_threshold:
                continue
            classifications.append({
                "label": self._get_label(int(idx)),
                "confidence": round(conf, 4),
                "class_index": int(idx),
            })

        if not classifications:
            return None

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "classification",
            "results": {"classifications": classifications},
            "inference_time_ms": inference_time_ms,
            "confidence_threshold": self.confidence_threshold,
        }

    def _publish(self, payload):
        try:
            encoded = json.dumps(payload).encode("utf-8")
            logger.info("Publishing %d bytes to %s (%s: %s results, %sms)",
                       len(encoded), self.pub_topic, payload.get("result_type"),
                       payload.get("results", {}).get("count", len(payload.get("results", {}).get("classifications", []))),
                       payload.get("inference_time_ms"))
            self.ipc_client.publish_to_iot_core(
                topic_name=self.pub_topic,
                qos="1",
                payload=encoded,
            )
        except Exception as e:
            logger.error("Failed to publish inference results: %s: %s", type(e).__name__, e)


if __name__ == "__main__":
    handler = InferenceHandler()
    handler.run()
