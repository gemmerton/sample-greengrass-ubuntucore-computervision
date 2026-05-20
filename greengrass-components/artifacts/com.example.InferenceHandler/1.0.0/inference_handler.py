"""InferenceHandler - Unified shadow-reactive inference for edge computer vision.

Captures frames from the camera at a configurable interval, reads active model
metadata from the model-config local shadow, calls OVMS gRPC for inference,
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
        self.model_metadata = None
        self.active_model_id = None

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
            if "inference_interval" in state:
                self.inference_interval = float(state["inference_interval"])
                logger.info("Inference interval updated to %ss", self.inference_interval)
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _switch_to_model(self, model_id):
        """Handle an explicit model switch request from shadow delta.

        Reads model metadata from reported state, switches, reports back,
        and clears desired.active_model to prevent delta feedback loops.
        """
        if not self.thing_name or not model_id:
            return
        if model_id == self.active_model_id:
            self._report_and_clear_desired()
            return
        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
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
            self._report_and_clear_desired()
        except Exception as e:
            logger.error("Failed to switch to model '%s': %s", model_id, e)

    def _report_and_clear_desired(self):
        """Report active_model to shadow reported state.

        Only updates reported.active_model. Does NOT clear desired — that
        creates version conflicts when the React app writes desired via the
        cloud API concurrently. Once reported matches desired, the delta
        resolves naturally without explicit clearing.

        Retries on failure since ShadowManager may not be ready immediately
        after startup.
        """
        if not self.thing_name or not self.active_model_id:
            return
        payload = json.dumps({
            "state": {
                "reported": {"active_model": self.active_model_id},
            }
        }).encode("utf-8")
        for attempt in range(3):
            try:
                self.ipc_client.update_thing_shadow(
                    thing_name=self.thing_name,
                    shadow_name=SHADOW_NAME,
                    payload=payload,
                )
                logger.info("Reported active_model=%s", self.active_model_id)
                return
            except Exception as e:
                if attempt < 2:
                    time.sleep(2)
                else:
                    logger.warning("Failed to report active_model after 3 attempts: %s", e)

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
        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
            reported = shadow.get("state", {}).get("reported", {})
            desired = shadow.get("state", {}).get("desired", {})

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
                logger.info("Model metadata: %s", json.dumps(metadata, indent=2))
                self._report_active_model()
            elif self.model_metadata is None:
                # Same model but metadata not loaded (first run)
                self.model_metadata = metadata
        except Exception as e:
            logger.error("Failed to load active model from shadow: %s", e)
            traceback.print_exc()

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
        if len(input_shape) == 4:
            _, c_or_h, h_or_w, w_or_c = input_shape
            if c_or_h <= 4:
                target_h, target_w = h_or_w, w_or_c
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                transposed = np.transpose(rgb, (2, 0, 1))
                return np.expand_dims(transposed, axis=0).astype(np.float32)
            else:
                target_h, target_w = c_or_h, h_or_w
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                return np.expand_dims(rgb, axis=0).astype(np.float32)
        resized = cv2.resize(frame, (224, 224))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return np.expand_dims(np.transpose(rgb, (2, 0, 1)), axis=0).astype(np.float32)

    def _postprocess(self, result, output_names, frame_width, frame_height, inference_time_ms):
        result_dict = self._normalize_result(result)
        if "detection_out" in output_names or self._is_detection_output(result_dict):
            return self._postprocess_detection(result_dict, frame_width, frame_height, inference_time_ms)
        else:
            return self._postprocess_classification(result_dict, inference_time_ms)

    # Known labels for demo models. In production, these would come from labels
    # files bundled with the model component.
    DETECTION_LABELS = {0: "background", 1: "person"}

    def _get_label(self, class_id):
        return self.DETECTION_LABELS.get(class_id, f"class_{class_id}")

    @staticmethod
    def _normalize_result(result):
        if isinstance(result, dict):
            return result
        if isinstance(result, np.ndarray):
            return {"output": result}
        return {"output": np.array(result)}

    def _is_detection_output(self, result_dict):
        for key, val in result_dict.items():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[2] > 1 and val.shape[3] == 7:
                return True
        return False

    def _postprocess_detection(self, result_dict, frame_width, frame_height, inference_time_ms):
        output = None
        for key, val in result_dict.items():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[3] == 7:
                output = val
                break
        if output is None:
            for key, val in result_dict.items():
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
            label = self._get_label(label_id)
            detections.append({
                "label": label,
                "score": round(confidence, 4),
                "box": {
                    "xmin": round(xmin, 4),
                    "ymin": round(ymin, 4),
                    "xmax": round(xmax, 4),
                    "ymax": round(ymax, 4),
                },
            })

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
                "label": f"class_{idx}",
                "confidence": round(conf, 4),
                "class_index": int(idx),
            })

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
            self.ipc_client.publish_to_iot_core(
                topic_name=self.pub_topic,
                qos="1",
                payload=encoded,
            )
            logger.info("Published to %s (%s: %s results, %sms)",
                       self.pub_topic, payload.get("result_type"),
                       payload.get("results", {}).get("count", len(payload.get("results", {}).get("classifications", []))),
                       payload.get("inference_time_ms"))
        except Exception as e:
            logger.error("Failed to publish inference results: %s", e)


if __name__ == "__main__":
    handler = InferenceHandler()
    handler.run()
