"""VlmHandler - VLM inference via inference snap HTTP API for edge scene risk analysis.

Calls the VLM inference snap's OpenAI-compatible API (/v1/chat/completions) with
camera snapshots, parses structured risk assessments, and publishes results to
camera/vlm via IoT Core MQTT.
"""

import os
import sys
import time
import json
import logging
import traceback
import glob
import base64

import requests
import awsiot.greengrasscoreipc.clientv2 as clientv2

sys.path.insert(0, os.path.dirname(__file__))
from cloud_shadow import CloudShadowClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "vlm-config"
VLM_TOPIC = "camera/vlm"


class VlmHandler:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.snapshot_dir = os.environ.get(
            "SNAPSHOT_DIR",
            "/var/snap/aws-iot-greengrass/common/greengrass/v2/work/com.example.KvsProducer/snapshots"
        )
        self.vlm_endpoint = os.environ.get("VLM_ENDPOINT", "http://localhost:9090/v3/chat/completions")
        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.shadow_client = CloudShadowClient(self.thing_name, SHADOW_NAME)

        self.active_model_id = None
        self.system_prompt = ""
        self.user_prompt = ""
        self.inference_interval = 15
        self.max_tokens = 256

        logger.info(
            "VlmHandler initialized: thing=%s snapshot_dir=%s endpoint=%s",
            self.thing_name, self.snapshot_dir, self.vlm_endpoint,
        )

    def run(self):
        self._subscribe_to_shadow_delta()
        self._load_config()

        while True:
            if not self._endpoint_healthy():
                logger.info("VLM endpoint not available at %s, waiting...", self.vlm_endpoint)
                time.sleep(10)
                continue

            try:
                self._inference_cycle()
            except Exception as e:
                logger.error("VLM inference cycle failed: %s", e)
                traceback.print_exc()

            time.sleep(self.inference_interval)

    def _endpoint_healthy(self):
        try:
            base_url = self.vlm_endpoint.rsplit("/v1/", 1)[0]
            resp = requests.get(f"{base_url}/v2/health/live", timeout=3)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

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

            if "active_model" in state:
                new_model = state["active_model"]
                if new_model != self.active_model_id:
                    self.active_model_id = new_model
                    logger.info("Active VLM model set to: %s", new_model)
                    self._report_active_model()
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _load_config(self):
        shadow = self.shadow_client.get_shadow()
        reported = shadow.get("state", {}).get("reported", {})
        desired = shadow.get("state", {}).get("desired", {})

        vlm_config = reported.get("vlm_config") or desired.get("vlm_config") or {}
        self.system_prompt = vlm_config.get("system_prompt", "")
        self.user_prompt = vlm_config.get("user_prompt", "")
        self.inference_interval = vlm_config.get("inference_interval", 15)
        self.max_tokens = vlm_config.get("max_tokens", 256)

        self.active_model_id = (
            desired.get("active_model")
            or reported.get("active_model")
            or "gemma3"
        )

        if not reported.get("vlm_config") and self.system_prompt:
            self._report_vlm_config()
        self._report_active_model()

    def _inference_cycle(self):
        image_b64 = self._get_latest_snapshot_b64()
        if image_b64 is None:
            return

        start_time = time.time()

        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})

        user_content = []
        user_content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        })
        user_content.append({
            "type": "text",
            "text": self.user_prompt or "Describe what you see in this image.",
        })
        messages.append({"role": "user", "content": user_content})

        request_body = {
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
        }

        try:
            resp = requests.post(
                self.vlm_endpoint,
                json=request_body,
                timeout=120,
            )
            resp.raise_for_status()
            result = resp.json()
        except requests.RequestException as e:
            logger.error("VLM API request failed: %s", e)
            return

        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        raw_output = result.get("choices", [{}])[0].get("message", {}).get("content", "")
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

    def _get_latest_snapshot_b64(self):
        if not os.path.isdir(self.snapshot_dir):
            return None
        try:
            snapshots = sorted(glob.glob(os.path.join(self.snapshot_dir, "snapshot_*.jpg")))
            if not snapshots:
                return None
            latest = snapshots[-1]
            if time.time() - os.path.getmtime(latest) > 30:
                return None
            with open(latest, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
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

    def _report_active_model(self):
        if self.active_model_id:
            self.shadow_client.update_reported({"active_model": self.active_model_id})

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
