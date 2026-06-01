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
QUERY_TOPIC = "camera/vlm-query"
RESPONSE_TOPIC = "camera/vlm-response"


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
        self._serving_model_name = None
        self.system_prompt = ""
        self.user_prompt = ""
        self.inference_interval = 15
        self.max_tokens = 512

        self.mode = 'continuous'
        self.trigger_classes = ['person']
        self.trigger_cooldown = 10
        self.alert_rules = []
        self._last_trigger_time = 0
        self._pending_query = None

        logger.info(
            "VlmHandler initialized: thing=%s snapshot_dir=%s endpoint=%s",
            self.thing_name, self.snapshot_dir, self.vlm_endpoint,
        )

    def run(self):
        self._subscribe_to_shadow_delta()
        self._subscribe_to_cv_inference()
        self._subscribe_to_queries()
        self._load_config()

        while True:
            if not self._endpoint_healthy():
                logger.info("VLM endpoint not available at %s, waiting...", self.vlm_endpoint)
                time.sleep(10)
                continue

            # Handle pending query (pre-empts scheduled assessment)
            if self._pending_query:
                try:
                    self._handle_query(self._pending_query)
                except Exception as e:
                    logger.error("Query handling failed: %s", e)
                self._pending_query = None

            # Only run scheduled inference in continuous mode
            if self.mode == 'continuous':
                try:
                    self._inference_cycle()
                except Exception as e:
                    logger.error("VLM inference cycle failed: %s", e)
                    traceback.print_exc()

            time.sleep(self.inference_interval)

    def _get_base_url(self):
        from urllib.parse import urlparse
        parsed = urlparse(self.vlm_endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _endpoint_healthy(self):
        try:
            base_url = self._get_base_url()
            resp = requests.get(f"{base_url}/v2/health/live", timeout=3)
            if resp.status_code == 200:
                self._discover_model_name()
                return True
            return False
        except (requests.ConnectionError, requests.Timeout):
            return False

    def _discover_model_name(self):
        """Query the /v3/models endpoint to get the actual pipeline model name."""
        try:
            base_url = self._get_base_url()
            resp = requests.get(f"{base_url}/v3/models", timeout=3)
            if resp.status_code == 200:
                data = resp.json()
                models = data.get("data", [])
                if models:
                    self._serving_model_name = models[0].get("id")
        except Exception:
            pass

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
                self._apply_vlm_config(state["vlm_config"])

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
        self.max_tokens = vlm_config.get("max_tokens", 512)
        self.mode = vlm_config.get("mode", "continuous")
        self.trigger_classes = vlm_config.get("trigger_classes", ["person"])
        self.trigger_cooldown = vlm_config.get("trigger_cooldown", 10)
        self.alert_rules = vlm_config.get("alert_rules", [])

        self.active_model_id = (
            desired.get("active_model")
            or reported.get("active_model")
            or "gemma3"
        )

        if not reported.get("vlm_config") and self.system_prompt:
            self._report_vlm_config()
        self._report_active_model()

    def _apply_vlm_config(self, vlm_config):
        """Apply VLM config fields from shadow delta or initial load."""
        if vlm_config.get("system_prompt"):
            self.system_prompt = vlm_config["system_prompt"]
        if vlm_config.get("user_prompt"):
            self.user_prompt = vlm_config["user_prompt"]
        if vlm_config.get("inference_interval"):
            self.inference_interval = int(vlm_config["inference_interval"])
        if vlm_config.get("max_tokens"):
            self.max_tokens = int(vlm_config["max_tokens"])
        if "mode" in vlm_config:
            self.mode = vlm_config["mode"]
        if "trigger_classes" in vlm_config:
            self.trigger_classes = vlm_config["trigger_classes"]
        if "trigger_cooldown" in vlm_config:
            self.trigger_cooldown = int(vlm_config["trigger_cooldown"])
        if "alert_rules" in vlm_config:
            self.alert_rules = vlm_config["alert_rules"]
        logger.info("VLM config updated: mode=%s, interval=%ds, trigger_classes=%s",
                    self.mode, self.inference_interval, self.trigger_classes)
        self._report_vlm_config()

    def _should_trigger(self, detections):
        """Check if CV detections should trigger a VLM assessment."""
        if self.mode != 'triggered':
            return False
        now = time.time()
        if now - self._last_trigger_time < self.trigger_cooldown:
            return False
        for det in detections:
            if det.get('label', '').lower() in [c.lower() for c in self.trigger_classes]:
                return True
        return False

    def _build_system_prompt(self):
        """Build the full system prompt, injecting alert rules if defined."""
        prompt = self.system_prompt
        if not self.alert_rules:
            return prompt
        rules_text = "\n".join(f"{i+1}. {rule}" for i, rule in enumerate(self.alert_rules) if rule.strip())
        if not rules_text:
            return prompt
        prompt += (
            "\n\n---\nSEPARATE TASK - ALERT RULES (do NOT mix these into the risks array above):\n"
            "After completing the risk assessment, also check the following alert rules against the image. "
            "Alert rules are NOT safety risks - do not include them in the risks array. "
            "Add a separate \"alerts\" array to your JSON. "
            "For each rule that is TRUE, add: {\"rule\": \"exact rule text\", \"triggered\": true, \"detail\": \"one sentence\"}. "
            "If no rules are triggered, set \"alerts\": [].\n\n"
            f"Alert rules to check:\n{rules_text}"
        )
        return prompt

    def _subscribe_to_queries(self):
        """Subscribe to scene query topic."""
        self.ipc_client.subscribe_to_iot_core(
            topic_name=QUERY_TOPIC,
            qos="1",
            on_stream_event=self._on_query_message,
            on_stream_error=lambda e: logger.error("Query stream error: %s", e),
            on_stream_closed=lambda: logger.warning("Query stream closed"),
        )
        logger.info("Subscribed to query topic: %s", QUERY_TOPIC)

    def _on_query_message(self, event):
        """Receive a scene query — stores latest only."""
        try:
            payload = json.loads(event.message.payload)
            if 'query_id' in payload and 'question' in payload:
                self._pending_query = payload
                logger.info("Query received: %s", payload.get('question', '')[:80])
        except Exception as e:
            logger.error("Failed to parse query message: %s", e)

    def _handle_query(self, query):
        """Process a scene query: send question + image to VLM, publish response."""
        image_b64 = self._get_latest_snapshot_b64()
        if image_b64 is None:
            logger.warning("No snapshot available for query")
            return

        start_time = time.time()

        messages = [
            {"role": "system", "content": "Answer the user's question about the image concisely and factually."},
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": query["question"]},
            ]},
        ]

        request_body = {
            "model": self._serving_model_name or self.active_model_id,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
            "stream": False,
        }

        try:
            resp = requests.post(self.vlm_endpoint, json=request_body, timeout=120)
            if resp.status_code != 200:
                logger.error("VLM query API error %d: %s", resp.status_code, resp.text[:200])
                return
            result = resp.json()
        except requests.RequestException as e:
            logger.error("VLM query request failed: %s", e)
            return

        inference_time_ms = round((time.time() - start_time) * 1000, 1)
        answer = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        response_payload = {
            "query_id": query["query_id"],
            "question": query["question"],
            "answer": answer,
            "timestamp": time.time(),
            "inference_time_ms": inference_time_ms,
        }

        try:
            encoded = json.dumps(response_payload).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=RESPONSE_TOPIC,
                qos="1",
                payload=encoded,
            )
            logger.info("Published query response: %s (%.1fs)", query["query_id"], inference_time_ms / 1000)
        except Exception as e:
            logger.error("Failed to publish query response: %s", e)

    def _subscribe_to_cv_inference(self):
        """Subscribe to camera/inference to receive CV detection results."""
        cv_topic = "camera/inference"
        self.ipc_client.subscribe_to_iot_core(
            topic_name=cv_topic,
            qos="1",
            on_stream_event=self._on_cv_inference,
            on_stream_error=lambda e: logger.error("CV inference stream error: %s", e),
            on_stream_closed=lambda: logger.warning("CV inference stream closed"),
        )
        logger.info("Subscribed to CV inference: %s", cv_topic)

    def _on_cv_inference(self, event):
        """Handle incoming CV inference results — trigger VLM if configured."""
        if self.mode != 'triggered':
            return
        try:
            payload = json.loads(event.message.payload)
            detections = payload.get("results", {}).get("detections", [])
            if self._should_trigger(detections):
                self._last_trigger_time = time.time()
                logger.info("CV trigger fired: detected matching classes")
                self._inference_cycle()
        except Exception as e:
            logger.error("Failed to handle CV inference event: %s", e)

    def _inference_cycle(self):
        image_b64 = self._get_latest_snapshot_b64()
        if image_b64 is None:
            return

        start_time = time.time()

        messages = []
        system_prompt = self._build_system_prompt()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

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
            "model": self._serving_model_name or self.active_model_id,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": 0.1,
            "stream": False,
        }

        try:
            resp = requests.post(
                self.vlm_endpoint,
                json=request_body,
                timeout=120,
            )
            if resp.status_code != 200:
                logger.error("VLM API error %d: %s", resp.status_code, resp.text[:200])
                return
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
                raw_alerts = parsed.get("alerts", [])
                validated_alerts = [
                    a for a in raw_alerts
                    if isinstance(a, dict)
                    and a.get("triggered")
                    and a.get("rule", "") in self.alert_rules
                ]
                return {
                    "risk_level": parsed["risk_level"],
                    "summary": parsed["summary"],
                    "risks": parsed.get("risks", []),
                    "alerts": validated_alerts,
                }
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
                "mode": self.mode,
                "trigger_classes": self.trigger_classes,
                "trigger_cooldown": self.trigger_cooldown,
                "alert_rules": self.alert_rules,
            }
        })


if __name__ == "__main__":
    handler = VlmHandler()
    handler.run()
