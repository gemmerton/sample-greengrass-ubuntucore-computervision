"""VlmModelManager - manages VLM inference snap lifecycle (install, switch, status).

Subscribes to the vlm-config named shadow delta. Installs VLM snaps from the
Snap Store, switches the active model by stopping/starting snap services,
and reports model status to the shadow.
"""

import os
import sys
import time
import json
import logging
import traceback

import requests
import awsiot.greengrasscoreipc.clientv2 as clientv2

sys.path.insert(0, os.path.dirname(__file__))
from cloud_shadow import CloudShadowClient
from snapd_client import SnapdClient, SnapdError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "vlm-config"


class VlmModelManager:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.vlm_port = int(os.environ.get("VLM_PORT", "9090"))
        self.install_timeout = int(os.environ.get("INSTALL_TIMEOUT", "900"))
        self.health_check_timeout = int(os.environ.get("HEALTH_CHECK_TIMEOUT", "120"))

        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.shadow_client = CloudShadowClient(self.thing_name, SHADOW_NAME)
        self.snapd = SnapdClient()
        self.reported_models = {}
        self.active_model = None

        logger.info(
            "VlmModelManager initialized: thing_name=%s, port=%d",
            self.thing_name, self.vlm_port,
        )

    def run(self):
        self._load_current_state()
        self._subscribe_to_shadow_delta()
        self._reconcile_on_startup()

        logger.info("VlmModelManager running, waiting for shadow delta events...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("VlmModelManager stopped")

    def _load_current_state(self):
        shadow = self.shadow_client.get_shadow()
        state = shadow.get("state", {})
        reported = state.get("reported", {})
        desired = state.get("desired", {})
        self.reported_models = reported.get("models", {})
        self.active_model = reported.get("active_model")

        # If no active model reported but endpoint is healthy, adopt the
        # desired active_model as current (service is already running)
        if not self.active_model and self._wait_for_healthy_quick():
            desired_active = desired.get("active_model")
            if desired_active and self.snapd.is_installed(desired_active):
                self.active_model = desired_active
                self._report_active_model(desired_active)
                logger.info("Detected running VLM model: %s", desired_active)

        logger.info(
            "Loaded state: models=%s, active=%s",
            list(self.reported_models.keys()), self.active_model,
        )

        # Stop all non-active VLM snap services to prevent port conflicts
        self._stop_non_active_services()

    def _stop_non_active_services(self):
        """Stop all installed VLM snap services that are not the active model.

        Prevents port 9090 conflicts when multiple VLM snaps have their services
        auto-enabled (e.g. after snap install/refresh).
        """
        for model_id in self.reported_models:
            if model_id == self.active_model:
                continue
            if self.reported_models[model_id].get("status") != "ready":
                continue
            try:
                if self.snapd.is_installed(model_id):
                    self.snapd.stop_snap_service(model_id)
                    logger.info("Stopped non-active VLM snap '%s' to prevent port conflict", model_id)
            except Exception as e:
                logger.warning("Failed to stop non-active snap '%s': %s", model_id, e)

    def _subscribe_to_shadow_delta(self):
        if not self.thing_name:
            logger.error("AWS_IOT_THING_NAME not set")
            return
        delta_topic = (
            f"$aws/things/{self.thing_name}/shadow/name/{SHADOW_NAME}/update/delta"
        )
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
            logger.info("Shadow delta received: %s", json.dumps(state, indent=2))

            if "models" in state:
                self._reconcile_models(state["models"])

            if "active_model" in state:
                self._handle_active_model_switch(state["active_model"])

            if "vlm_config" in state:
                self._report_vlm_config(state["vlm_config"])

        except Exception:
            logger.error("Error processing shadow delta")
            traceback.print_exc()

    def _reconcile_on_startup(self):
        shadow = self.shadow_client.get_shadow()
        if not shadow:
            return

        state = shadow.get("state", {})
        desired = state.get("desired", {})
        delta = state.get("delta", {})

        if not desired and not delta:
            return

        logger.info("Startup reconciliation: checking pending desired state")

        desired_models = desired.get("models", {})
        if desired_models:
            self._reconcile_models(desired_models)

        if "active_model" in delta:
            self._handle_active_model_switch(delta["active_model"])

    def _reconcile_models(self, desired_models):
        desired_ids = set(desired_models.keys())

        to_install = {}
        for model_id in desired_ids:
            status = self.reported_models.get(model_id, {}).get("status")
            if status not in ("ready", "installing"):
                to_install[model_id] = desired_models[model_id]

        if to_install:
            logger.info("Models to install: %s", list(to_install.keys()))

        for model_id, config in to_install.items():
            source = config.get("source", "snap")
            if source == "s3-snap":
                self._install_s3_snap(model_id, config)
            else:
                self._install_vlm_snap(model_id, config)

    def _configure_vlm_port(self, model_id):
        """Configure a VLM snap to use the standard VLM port via its CLI."""
        import subprocess
        try:
            subprocess.run(
                [model_id, "set", f"http.port={self.vlm_port}"],
                capture_output=True, timeout=10, check=True,
            )
            subprocess.run(
                [model_id, "set", "http.host=0.0.0.0"],
                capture_output=True, timeout=10, check=True,
            )
            logger.info("Configured snap '%s' to use port %d", model_id, self.vlm_port)
        except FileNotFoundError:
            logger.warning("Snap CLI '%s' not found, trying snapd conf API", model_id)
            try:
                self.snapd.set_snap_conf(model_id, {
                    "http.port": self.vlm_port,
                    "http.host": "0.0.0.0",
                })
            except Exception as e:
                logger.warning("Could not configure port for snap '%s': %s", model_id, e)
        except Exception as e:
            logger.warning("Could not configure port for snap '%s': %s", model_id, e)

    def _install_vlm_snap(self, model_id, config):
        channel = config.get("channel", "stable")

        if self.snapd.is_installed(model_id):
            logger.info("Snap '%s' already installed", model_id)
            self._configure_vlm_port(model_id)
            self._report_model_status(model_id, "ready", channel=channel)
            if model_id != self.active_model:
                try:
                    self.snapd.stop_snap_service(model_id)
                except Exception:
                    pass
            return

        self._report_model_status(model_id, "installing", channel=channel)

        try:
            self.snapd.install_snap(
                model_id, channel=channel, timeout=self.install_timeout
            )
            logger.info("Snap '%s' installed successfully", model_id)
        except SnapdError as e:
            # Timeout may occur while model weights are still downloading,
            # but the snap itself may already be installed and usable
            if "timed out" in str(e) and self.snapd.is_installed(model_id):
                logger.warning(
                    "Snap '%s' install timed out but snap is present - treating as ready",
                    model_id,
                )
            else:
                logger.error("Failed to install snap '%s': %s", model_id, e)
                self._report_model_status(
                    model_id, "failed", channel=channel, reason=str(e)
                )
                return
        except Exception as e:
            logger.error("Unexpected error installing snap '%s': %s", model_id, e)
            self._report_model_status(
                model_id, "failed", channel=channel, reason=str(e)
            )
            return

        # Configure standard port
        self._configure_vlm_port(model_id)

        # Stop service immediately unless this is the intended active model
        if model_id != self.active_model:
            try:
                self.snapd.stop_snap_service(model_id)
                logger.info(
                    "Stopped snap '%s' service (not the active model)", model_id
                )
            except Exception as e:
                logger.warning(
                    "Could not stop snap '%s' after install: %s", model_id, e
                )

        self._report_model_status(model_id, "ready", channel=channel)

    def _download_from_s3(self, s3_uri, model_id, suffix):
        """Download a file from S3 to a temporary local path."""
        import boto3
        from urllib.parse import urlparse

        parsed = urlparse(s3_uri)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        local_path = f"/tmp/{model_id}{suffix}"

        logger.info("Downloading s3://%s/%s -> %s", bucket, key, local_path)
        s3_client = boto3.client("s3")
        s3_client.download_file(bucket, key, local_path)
        return local_path

    def _install_s3_snap(self, model_id, config):
        """Install a VLM snap and its components from S3.

        Downloads the .snap file and .comp files from S3, sideloads them via
        the snapd API. After installation the snap behaves identically to a
        store-installed snap.
        """
        snap_s3_uri = config.get("s3_uri")
        components_s3 = config.get("components_s3", {})

        if not snap_s3_uri:
            logger.error("s3-snap model '%s' missing 's3_uri' field", model_id)
            self._report_model_status(model_id, "failed", reason="Missing s3_uri")
            return

        if self.snapd.is_installed(model_id):
            logger.info("Snap '%s' already installed", model_id)
            self._configure_vlm_port(model_id)
            self._report_model_status(model_id, "ready")
            if model_id != self.active_model:
                try:
                    self.snapd.stop_snap_service(model_id)
                except Exception:
                    pass
            return

        self._report_model_status(model_id, "installing")

        # Download and sideload the parent snap
        try:
            local_snap = self._download_from_s3(snap_s3_uri, model_id, ".snap")
            self.snapd.sideload_component(local_snap, timeout=300)
            os.remove(local_snap)
            logger.info("Sideloaded snap '%s' from S3", model_id)
        except Exception as e:
            logger.error("Failed to sideload snap '%s': %s", model_id, e)
            self._report_model_status(model_id, "failed", reason=f"Snap sideload failed: {e}")
            return

        # Download and sideload each component
        for comp_name, comp_s3_uri in components_s3.items():
            try:
                local_comp = self._download_from_s3(comp_s3_uri, model_id, f"+{comp_name}.comp")
                self.snapd.sideload_component(local_comp, timeout=900)
                os.remove(local_comp)
                logger.info("Sideloaded component '%s+%s' from S3", model_id, comp_name)
            except Exception as e:
                logger.error("Failed to sideload component '%s+%s': %s", model_id, comp_name, e)
                self._report_model_status(model_id, "failed", reason=f"Component sideload failed: {e}")
                return

        # Configure and report ready
        self._configure_vlm_port(model_id)
        self._report_model_status(model_id, "ready")

        if model_id != self.active_model:
            try:
                self.snapd.stop_snap_service(model_id)
            except Exception:
                pass

        logger.info("S3-snap model '%s' installed successfully", model_id)

    def _handle_active_model_switch(self, new_model_id):
        if not new_model_id:
            return

        if new_model_id == self.active_model:
            logger.info("Model '%s' is already active, no-op", new_model_id)
            self._report_active_model(new_model_id)
            self._clear_desired_field("active_model")
            return

        model_entry = self.reported_models.get(new_model_id, {})
        if model_entry.get("status") != "ready":
            logger.warning(
                "Cannot switch to '%s' - status is '%s'",
                new_model_id, model_entry.get("status", "not_installed"),
            )
            self._clear_desired_field("active_model")
            return

        logger.info(
            "Switching active VLM model: %s -> %s", self.active_model, new_model_id
        )

        # Stop current active model
        if self.active_model:
            try:
                self.snapd.stop_snap_service(self.active_model)
                logger.info("Stopped snap '%s'", self.active_model)
            except Exception as e:
                logger.warning("Failed to stop snap '%s': %s", self.active_model, e)

        # Configure port on new model before starting
        self._configure_vlm_port(new_model_id)

        # Start new model
        try:
            self.snapd.start_snap_service(new_model_id)
            logger.info("Started snap '%s'", new_model_id)
        except SnapdError as e:
            logger.error("Failed to start snap '%s': %s", new_model_id, e)
            if self.active_model:
                try:
                    self.snapd.start_snap_service(self.active_model)
                except Exception:
                    pass
            self._clear_desired_field("active_model")
            return

        # Wait for health check
        if self._wait_for_healthy():
            self.active_model = new_model_id
            self._report_active_model(new_model_id)
            self._clear_desired_field("active_model")
            logger.info("VLM model switch to '%s' complete", new_model_id)
        else:
            logger.error(
                "Model '%s' did not become healthy after start", new_model_id
            )
            try:
                self.snapd.stop_snap_service(new_model_id)
            except Exception:
                pass
            if self.active_model:
                try:
                    self.snapd.start_snap_service(self.active_model)
                except Exception:
                    pass
            self._clear_desired_field("active_model")

    def _wait_for_healthy(self):
        url = f"http://localhost:{self.vlm_port}/v2/health/live"
        deadline = time.time() + self.health_check_timeout
        while time.time() < deadline:
            try:
                resp = requests.get(url, timeout=3)
                if resp.status_code == 200:
                    return True
            except (requests.ConnectionError, requests.Timeout):
                pass
            time.sleep(5)
        return False

    def _wait_for_healthy_quick(self):
        """Quick single-shot health check (no retry loop)."""
        url = f"http://localhost:{self.vlm_port}/v2/health/live"
        try:
            resp = requests.get(url, timeout=3)
            return resp.status_code == 200
        except (requests.ConnectionError, requests.Timeout):
            return False

    def _report_model_status(self, model_id, status, channel=None, reason=None):
        entry = {"status": status}
        if channel:
            entry["channel"] = channel
        if reason:
            entry["reason"] = reason

        self.reported_models[model_id] = entry
        self.shadow_client.update_reported({"models": self.reported_models})

    def _report_active_model(self, model_id):
        self.shadow_client.update_reported({"active_model": model_id})

    def _report_vlm_config(self, vlm_config):
        self.shadow_client.update_reported({"vlm_config": vlm_config})
        self._clear_desired_field("vlm_config")

    def _clear_desired_field(self, field):
        try:
            import boto3
            iot_data = boto3.client(
                "iot-data",
                region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-1"),
            )
            iot_data.update_thing_shadow(
                thingName=self.thing_name,
                shadowName=SHADOW_NAME,
                payload=json.dumps(
                    {"state": {"desired": {field: None}}}
                ).encode("utf-8"),
            )
        except Exception as e:
            logger.warning("Failed to clear desired.%s: %s", field, e)


if __name__ == "__main__":
    manager = VlmModelManager()
    manager.run()
