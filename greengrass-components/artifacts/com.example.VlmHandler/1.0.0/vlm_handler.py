"""VlmHandler - OpenVINO GenAI VLM inference for edge scene risk analysis.

Loads a VLM model via openvino_genai.VLMPipeline, captures frames from the
shared snapshot directory on a configurable interval, generates structured
risk assessments, and publishes results to camera/vlm via IoT Core MQTT.
"""

import os
import sys
import time
import json
import logging
import traceback
import glob

from PIL import Image
import openvino_genai
import awsiot.greengrasscoreipc.clientv2 as clientv2

sys.path.insert(0, os.path.dirname(__file__))
from cloud_shadow import CloudShadowClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"
VLM_TOPIC = "camera/vlm"


class VlmHandler:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.snapshot_dir = os.environ.get(
            "SNAPSHOT_DIR",
            "/var/snap/aws-iot-greengrass/common/greengrass/v2/work/com.example.KvsProducer/snapshots"
        )
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.shadow_client = CloudShadowClient(self.thing_name, SHADOW_NAME)

        self.pipeline = None
        self.active_model_id = None
        self.system_prompt = ""
        self.user_prompt = ""
        self.inference_interval = 15
        self.max_tokens = 256

        logger.info("VlmHandler initialized: thing=%s snapshot_dir=%s", self.thing_name, self.snapshot_dir)

    def run(self):
        self._subscribe_to_shadow_delta()
        self._load_config_and_model()

        while True:
            if self.pipeline is None:
                logger.info("No VLM model loaded, waiting...")
                time.sleep(5)
                self._load_config_and_model()
                continue

            try:
                self._inference_cycle()
            except Exception as e:
                logger.error("VLM inference cycle failed: %s", e)
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

            if "vlm_config" in state:
                vlm_config = state["vlm_config"]
                if vlm_config.get("system_prompt"):
                    self.system_prompt = vlm_config["system_prompt"]
                if vlm_config.get("user_prompt"):
                    self.user_prompt = vlm_config["user_prompt"]
                if vlm_config.get("inference_interval"):
                    self.inference_interval = int(vlm_config["inference_interval"])
                if vlm_config.get("max_tokens"):
                    self.max_tokens = int(vlm_config["max_tokens"])
                logger.info("VLM config updated: interval=%ds, max_tokens=%d", self.inference_interval, self.max_tokens)
                self._report_vlm_config()

            if "active_vlm_model" in state:
                new_model = state["active_vlm_model"]
                if new_model != self.active_model_id:
                    logger.info("VLM model switch requested: %s -> %s", self.active_model_id, new_model)
                    self._switch_model(new_model)
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _load_config_and_model(self):
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        desired = shadow.get("state", {}).get("desired", {})

        vlm_config = reported.get("vlm_config") or desired.get("vlm_config") or {}
        self.system_prompt = vlm_config.get("system_prompt", "")
        self.user_prompt = vlm_config.get("user_prompt", "")
        self.inference_interval = vlm_config.get("inference_interval", 15)
        self.max_tokens = vlm_config.get("max_tokens", 256)

        target_model_id = desired.get("active_vlm_model") or reported.get("active_vlm_model")
        if not target_model_id:
            models = reported.get("models", {})
            target_model_id = next(
                (mid for mid, m in models.items()
                 if isinstance(m, dict) and m.get("type") == "vlm" and m.get("status") == "ready"),
                None,
            )

        if target_model_id and target_model_id != self.active_model_id:
            self._switch_model(target_model_id)

    def _switch_model(self, model_id):
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        models = reported.get("models", {})

        if model_id not in models:
            logger.warning("VLM model '%s' not in inventory", model_id)
            return

        entry = models[model_id]
        if entry.get("status") != "ready":
            logger.warning("VLM model '%s' not ready (status=%s)", model_id, entry.get("status"))
            return

        model_path = entry.get("model_metadata", {}).get("local_path")
        if not model_path:
            logger.error("VLM model '%s' has no local_path", model_id)
            return

        logger.info("Loading VLM model '%s' from %s", model_id, model_path)
        try:
            self.pipeline = openvino_genai.VLMPipeline(model_path, "CPU")
            self.active_model_id = model_id
            logger.info("VLM model '%s' loaded successfully", model_id)
            self._report_active_vlm_model()
        except Exception as e:
            logger.error("Failed to load VLM model '%s': %s", model_id, e)
            self.pipeline = None

    def _inference_cycle(self):
        image = self._get_latest_snapshot()
        if image is None:
            return

        prompt = self._build_prompt()
        start_time = time.time()

        try:
            generation_config = openvino_genai.GenerationConfig()
            generation_config.max_new_tokens = self.max_tokens
            raw_output = self.pipeline.generate(prompt, image=image, generation_config=generation_config)
        except Exception as e:
            logger.error("VLM generation failed: %s", e)
            return

        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        response = self._parse_response(raw_output)

        payload = {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.active_model_id,
            "inference_time_ms": inference_time_ms,
            "prompt": {
                "system": self.system_prompt,
                "user": self.user_prompt,
            },
            "response": response,
            "raw_output": raw_output,
        }

        self._publish(payload)

    def _build_prompt(self):
        parts = []
        if self.system_prompt:
            parts.append(self.system_prompt)
        if self.user_prompt:
            parts.append(self.user_prompt)
        return "\n\n".join(parts) if parts else "Describe what you see in this image."

    def _parse_response(self, raw_output):
        try:
            text = raw_output.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()
            parsed = json.loads(text)
            if "risk_level" in parsed and "summary" in parsed:
                return parsed
        except (json.JSONDecodeError, IndexError, KeyError):
            pass
        return None

    def _get_latest_snapshot(self):
        if not os.path.isdir(self.snapshot_dir):
            return None
        try:
            snapshots = sorted(glob.glob(os.path.join(self.snapshot_dir, "snapshot_*.jpg")))
            if not snapshots:
                return None
            latest = snapshots[-1]
            if time.time() - os.path.getmtime(latest) > 30:
                return None
            return Image.open(latest)
        except Exception as e:
            logger.error("Failed to read snapshot: %s", e)
            return None

    def _publish(self, payload):
        try:
            encoded = json.dumps(payload).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=VLM_TOPIC,
                qos="1",
                payload=encoded,
            )
            risk = payload.get("response", {})
            risk_level = risk.get("risk_level", "N/A") if risk else "PARSE_FAIL"
            logger.info("Published VLM result: risk=%s, time=%.1fs", risk_level, payload["inference_time_ms"] / 1000)
        except Exception as e:
            logger.error("Failed to publish VLM result: %s", e)

    def _report_active_vlm_model(self):
        if self.active_model_id:
            self.shadow_client.update_reported({"active_vlm_model": self.active_model_id})

    def _report_vlm_config(self):
        self.shadow_client.update_reported({
            "vlm_config": {
                "system_prompt": self.system_prompt,
                "user_prompt": self.user_prompt,
                "inference_interval": self.inference_interval,
                "max_tokens": self.max_tokens,
            }
        })


if __name__ == "__main__":
    handler = VlmHandler()
    handler.run()
