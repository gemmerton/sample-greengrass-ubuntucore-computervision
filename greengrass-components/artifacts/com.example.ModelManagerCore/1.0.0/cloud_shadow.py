"""Cloud shadow client - direct IoT Data Plane access bypassing local ShadowManager.

All shadow reads and writes go directly to the AWS IoT Core cloud shadow via the
IoT Data Plane API (boto3). This eliminates the ShadowManager sync layer and the
race conditions that come with eventual consistency between local and cloud state.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger(__name__)


class CloudShadowClient:
    """Thin wrapper around IoT Data Plane for named shadow get/update."""

    def __init__(self, thing_name: str, shadow_name: str):
        self._thing_name = thing_name
        self._shadow_name = shadow_name
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "eu-west-1")
        self._client = boto3.client("iot-data", region_name=region)

    def get_shadow(self) -> dict:
        """Get the full shadow document from the cloud.

        Returns:
            Parsed shadow document dict, or empty dict on failure.
        """
        try:
            response = self._client.get_thing_shadow(
                thingName=self._thing_name,
                shadowName=self._shadow_name,
            )
            return json.loads(response["payload"].read())
        except self._client.exceptions.ResourceNotFoundException:
            logger.info("Shadow '%s' not found for thing '%s'", self._shadow_name, self._thing_name)
            return {}
        except Exception as e:
            logger.error("Failed to get cloud shadow '%s': %s", self._shadow_name, e)
            return {}

    def update_reported(self, reported: dict) -> bool:
        """Update reported state in the cloud shadow.

        Args:
            reported: Dict to merge into reported state.

        Returns:
            True on success, False on failure.
        """
        payload = json.dumps({"state": {"reported": reported}}).encode("utf-8")
        try:
            self._client.update_thing_shadow(
                thingName=self._thing_name,
                shadowName=self._shadow_name,
                payload=payload,
            )
            return True
        except Exception as e:
            logger.error("Failed to update cloud shadow reported state: %s", e)
            return False

    def update_desired(self, desired: dict) -> bool:
        """Update desired state in the cloud shadow.

        Args:
            desired: Dict to merge into desired state (use None values to clear fields).

        Returns:
            True on success, False on failure.
        """
        payload = json.dumps({"state": {"desired": desired}}).encode("utf-8")
        try:
            self._client.update_thing_shadow(
                thingName=self._thing_name,
                shadowName=self._shadow_name,
                payload=payload,
            )
            return True
        except Exception as e:
            logger.error("Failed to update cloud shadow desired state: %s", e)
            return False
