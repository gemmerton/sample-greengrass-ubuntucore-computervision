#!/usr/bin/env python3
"""
New Edge Device Setup Script

Sets up a new Greengrass Core device with all required configuration for the
CV/VLM inference pipeline. This script handles:

1. Deploying Greengrass components (ModelManagerCore, InferenceHandler, KvsProducer, VlmHandler)
2. Creating named shadows (model-config, kvs-config, inference-config)
3. Configuring the ovms-engine snap (setting the active engine)

Prerequisites:
- Device must already be provisioned as a Greengrass Core device (IoT Thing exists)
- The ovms-engine and aws-iot-greengrass snaps must be installed on the device
- Snap content interfaces must be connected:
    snap connect aws-iot-greengrass:inference-config ovms-engine:inference-config
    snap connect aws-iot-greengrass:inference-models ovms-engine:inference-models
- SSH access to the device with the ubuntu_core_rsa key

Usage:
    python3 setup_new_device.py --thing-name <name> --device-ip <ip> [options]
"""

import argparse
import json
import subprocess
import sys
import time

import boto3
from botocore.exceptions import ClientError


DEFAULT_REGION = "eu-west-1"
DEFAULT_S3_BUCKET = "gg-ge-test"
DEFAULT_SSH_KEY = "/Users/gemmerto/local-dev/ubuntu-core/ubuntu_core_rsa"
DEFAULT_SSH_USER = "gemmerton"
DEFAULT_KVS_STREAM = "ge-demo-stream"
DEFAULT_ENGINE = "intel-cpu"

DESIRED_MODELS = {
    "faster-rcnn": {"source": "snap", "type": "cv"},
    "person-detection": {"source": "snap", "type": "cv"},
    "efficientnet": {"source": "snap", "type": "cv"},
}

KVS_CONFIG = {
    "stream_name": DEFAULT_KVS_STREAM,
    "frame_rate": 15,
    "resolution": "640x480",
    "streaming_enabled": True,
    "staleness_window_seconds": 30.0,
    "snapshot_interval_seconds": 1,
}

INFERENCE_CONFIG = {
    "confidence_threshold": 0.4,
}

MODEL_CONFIG_DESIRED = {
    "models": DESIRED_MODELS,
    "inference_interval": 1,
    "confidence_threshold": 0.4,
}


def ssh_command(device_ip, ssh_key, ssh_user, command, timeout=30):
    """Run a command on the device via SSH."""
    cmd = [
        "ssh",
        "-i", ssh_key,
        "-o", "StrictHostKeyChecking=no",
        "-o", f"ConnectTimeout={timeout}",
        f"{ssh_user}@{device_ip}",
        command,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
    return result


def wait_for_device(device_ip, ssh_key, ssh_user, timeout=120):
    """Wait for the device to be reachable via SSH."""
    print(f"Waiting for device at {device_ip} to be reachable...")
    start = time.time()
    while time.time() - start < timeout:
        result = ssh_command(device_ip, ssh_key, ssh_user, "echo ok", timeout=5)
        if result.returncode == 0:
            print("Device is reachable.")
            return True
        time.sleep(5)
    print("ERROR: Device not reachable within timeout.")
    return False


def deploy_components(thing_name, s3_bucket, region):
    """Deploy Greengrass components to the device."""
    print(f"\n{'='*60}")
    print("Step 1: Deploying Greengrass components")
    print(f"{'='*60}")

    from deploy_greengrass_components import GreengrassDeployer
    deployer = GreengrassDeployer(s3_bucket, region)
    deployer.validate_structure()
    components = deployer.create_all_components()
    deployment_id = deployer.create_deployment(thing_name, components)

    print(f"Deployment ID: {deployment_id}")
    print(f"Components: {[c['componentName'] for c in components]}")
    return deployment_id


def create_shadows(thing_name, region, kvs_stream_name):
    """Create the required named shadows for the device."""
    print(f"\n{'='*60}")
    print("Step 2: Creating named shadows")
    print(f"{'='*60}")

    iot_data = boto3.client("iot-data", region_name=region)

    kvs_config = dict(KVS_CONFIG)
    kvs_config["stream_name"] = kvs_stream_name

    shadows = {
        "model-config": {"state": {"desired": MODEL_CONFIG_DESIRED}},
        "kvs-config": {"state": {"desired": kvs_config}},
        "inference-config": {"state": {"desired": INFERENCE_CONFIG}},
    }

    for shadow_name, payload in shadows.items():
        try:
            existing = iot_data.get_thing_shadow(
                thingName=thing_name, shadowName=shadow_name
            )
            print(f"  Shadow '{shadow_name}' already exists (updating desired state)")
        except ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                print(f"  Creating shadow '{shadow_name}'")
            else:
                raise

        iot_data.update_thing_shadow(
            thingName=thing_name,
            shadowName=shadow_name,
            payload=json.dumps(payload).encode("utf-8"),
        )
        print(f"  ✓ Shadow '{shadow_name}' configured")


def configure_ovms_engine(device_ip, ssh_key, ssh_user, engine):
    """Configure the ovms-engine snap on the device."""
    print(f"\n{'='*60}")
    print("Step 3: Configuring ovms-engine snap")
    print(f"{'='*60}")

    # Check current engine setting
    result = ssh_command(device_ip, ssh_key, ssh_user, "sudo snap get ovms-engine engine 2>/dev/null")
    current_engine = result.stdout.strip() if result.returncode == 0 else ""

    if current_engine == engine:
        print(f"  Engine already set to '{engine}'")
    else:
        print(f"  Setting engine to '{engine}'...")
        result = ssh_command(device_ip, ssh_key, ssh_user, f"sudo snap set ovms-engine engine={engine}")
        if result.returncode != 0:
            print(f"  WARNING: Failed to set engine: {result.stderr}")
        else:
            print(f"  ✓ Engine set to '{engine}'")

    # Restart OVMS to pick up the engine setting
    print("  Restarting ovms-engine.server...")
    result = ssh_command(device_ip, ssh_key, ssh_user, "sudo snap restart ovms-engine.server")
    if result.returncode != 0:
        print(f"  WARNING: Failed to restart OVMS: {result.stderr}")
    else:
        print("  ✓ ovms-engine.server restarted")

    # Verify it's running
    time.sleep(3)
    result = ssh_command(device_ip, ssh_key, ssh_user, "sudo snap services ovms-engine.server")
    if "active" in result.stdout:
        print("  ✓ ovms-engine.server is active")
    else:
        print(f"  WARNING: ovms-engine.server may not be running: {result.stdout}")


def verify_snap_connections(device_ip, ssh_key, ssh_user):
    """Verify that required snap content interfaces are connected."""
    print(f"\n{'='*60}")
    print("Step 4: Verifying snap content interfaces")
    print(f"{'='*60}")

    result = ssh_command(device_ip, ssh_key, ssh_user, "sudo snap connections ovms-engine")
    if result.returncode != 0:
        print("  WARNING: Could not check snap connections")
        return False

    connections = result.stdout
    required = ["inference-config", "inference-models"]
    all_connected = True

    for interface in required:
        if interface in connections and "manual" in connections.split(interface)[1].split("\n")[0]:
            print(f"  ✓ {interface} connected")
        else:
            print(f"  ✗ {interface} NOT connected - run on device:")
            print(f"    sudo snap connect aws-iot-greengrass:{interface} ovms-engine:{interface}")
            all_connected = False

    return all_connected


def wait_for_deployment(thing_name, region, deployment_id, timeout=120):
    """Wait for the deployment to complete on the device."""
    print(f"\n{'='*60}")
    print("Step 5: Waiting for deployment to complete")
    print(f"{'='*60}")

    gg_client = boto3.client("greengrassv2", region_name=region)
    start = time.time()

    while time.time() - start < timeout:
        try:
            response = gg_client.get_deployment(deploymentId=deployment_id)
            status = response.get("deploymentStatus", "UNKNOWN")

            if status == "COMPLETED":
                print(f"  ✓ Deployment completed successfully")
                return True
            elif status in ("FAILED", "CANCELED"):
                print(f"  ✗ Deployment {status}")
                reason = response.get("statusReason", "Unknown reason")
                print(f"    Reason: {reason}")
                return False
            else:
                sys.stdout.write(f"\r  Deployment status: {status}...")
                sys.stdout.flush()
        except ClientError:
            pass

        time.sleep(10)

    print(f"\n  WARNING: Deployment did not complete within {timeout}s (may still be in progress)")
    return False


def verify_model_status(thing_name, region, timeout=90):
    """Wait for models to report ready status in the shadow."""
    print(f"\n{'='*60}")
    print("Step 6: Verifying model status")
    print(f"{'='*60}")

    iot_data = boto3.client("iot-data", region_name=region)
    start = time.time()

    while time.time() - start < timeout:
        try:
            response = iot_data.get_thing_shadow(
                thingName=thing_name, shadowName="model-config"
            )
            shadow = json.loads(response["payload"].read())
            reported = shadow.get("state", {}).get("reported", {})
            models = reported.get("models", {})

            if models:
                all_ready = all(
                    m.get("status") == "ready"
                    for m in models.values()
                    if isinstance(m, dict)
                )
                ready_count = sum(
                    1 for m in models.values()
                    if isinstance(m, dict) and m.get("status") == "ready"
                )

                if all_ready and ready_count == len(DESIRED_MODELS):
                    print(f"  ✓ All {ready_count} models ready:")
                    for name, info in models.items():
                        print(f"    - {name}: {info.get('status')}")
                    active = reported.get("active_model", "none")
                    print(f"  Active model: {active}")
                    return True
        except ClientError:
            pass

        time.sleep(10)

    # Print final status even if not all ready
    print(f"  Models not all ready within {timeout}s. Current status:")
    try:
        response = iot_data.get_thing_shadow(
            thingName=thing_name, shadowName="model-config"
        )
        shadow = json.loads(response["payload"].read())
        models = shadow.get("state", {}).get("reported", {}).get("models", {})
        for name, info in models.items():
            status = info.get("status", "unknown") if isinstance(info, dict) else "unknown"
            print(f"    - {name}: {status}")
    except Exception:
        print("    (could not read shadow)")
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Setup a new edge device for the CV/VLM inference pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--thing-name", required=True, help="IoT Thing name for the device")
    parser.add_argument("--device-ip", required=True, help="IP address of the device")
    parser.add_argument("--region", default=DEFAULT_REGION, help=f"AWS region (default: {DEFAULT_REGION})")
    parser.add_argument("--s3-bucket", default=DEFAULT_S3_BUCKET, help=f"S3 bucket (default: {DEFAULT_S3_BUCKET})")
    parser.add_argument("--ssh-key", default=DEFAULT_SSH_KEY, help="SSH private key path")
    parser.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help=f"SSH username (default: {DEFAULT_SSH_USER})")
    parser.add_argument("--kvs-stream", default=DEFAULT_KVS_STREAM, help=f"KVS stream name (default: {DEFAULT_KVS_STREAM})")
    parser.add_argument("--engine", default=DEFAULT_ENGINE, choices=["intel-cpu", "intel-gpu", "intel-npu"],
                        help=f"OVMS engine type (default: {DEFAULT_ENGINE})")
    parser.add_argument("--skip-deploy", action="store_true", help="Skip component deployment (shadows + device config only)")
    parser.add_argument("--skip-device", action="store_true", help="Skip SSH device configuration (deploy + shadows only)")

    args = parser.parse_args()

    print(f"Setting up device: {args.thing_name}")
    print(f"  Device IP: {args.device_ip}")
    print(f"  Region: {args.region}")
    print(f"  S3 Bucket: {args.s3_bucket}")
    print(f"  KVS Stream: {args.kvs_stream}")
    print(f"  Engine: {args.engine}")

    # Verify device is reachable (unless skipping device config)
    if not args.skip_device:
        if not wait_for_device(args.device_ip, args.ssh_key, args.ssh_user):
            sys.exit(1)

    # Step 1: Deploy components
    deployment_id = None
    if not args.skip_deploy:
        deployment_id = deploy_components(args.thing_name, args.s3_bucket, args.region)

    # Step 2: Create shadows
    create_shadows(args.thing_name, args.region, args.kvs_stream)

    # Step 3: Configure OVMS engine on device
    if not args.skip_device:
        verify_snap_connections(args.device_ip, args.ssh_key, args.ssh_user)
        configure_ovms_engine(args.device_ip, args.ssh_key, args.ssh_user, args.engine)

    # Step 4: Wait for deployment and verify
    if deployment_id:
        wait_for_deployment(args.thing_name, args.region, deployment_id)

    # Step 5: Verify models are ready
    print("\nWaiting for ModelManagerCore to reconcile and report models ready...")
    verify_model_status(args.thing_name, args.region)

    print(f"\n{'='*60}")
    print("Setup complete!")
    print(f"{'='*60}")
    print(f"\nDevice '{args.thing_name}' should now be operational.")
    print("Check the React dashboard to verify KVS stream and inference are working.")


if __name__ == "__main__":
    main()
