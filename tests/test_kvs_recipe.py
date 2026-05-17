import os
import yaml  # pip install pyyaml

RECIPE_PATH = os.path.join(os.path.dirname(__file__),
    "../greengrass-components/recipes/com.example.KvsProducer-1.0.0.yaml")

def load_recipe():
    with open(RECIPE_PATH) as f:
        return yaml.safe_load(f)

def test_recipe_file_exists():
    assert os.path.exists(RECIPE_PATH)

def test_recipe_declares_camera_handler_as_soft_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "com.example.CameraHandlerCore" in deps
    assert deps["com.example.CameraHandlerCore"]["DependencyType"] == "SOFT"

def test_recipe_declares_detection_handler_as_soft_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "com.example.DetectionHandler" in deps
    assert deps["com.example.DetectionHandler"]["DependencyType"] == "SOFT"

def test_recipe_declares_token_exchange_service_as_hard_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "aws.greengrass.TokenExchangeService" in deps
    dep_type = deps["aws.greengrass.TokenExchangeService"].get("DependencyType", "HARD")
    assert dep_type == "HARD"

def test_recipe_declares_shadow_manager_as_hard_dependency():
    r = load_recipe()
    deps = r["ComponentDependencies"]
    assert "aws.greengrass.ShadowManager" in deps

def test_recipe_grants_iot_core_subscribe_to_camera_detections():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    mqttproxy = ac.get("aws.greengrass.ipc.mqttproxy", {})
    all_resources = []
    for policy in mqttproxy.values():
        all_resources.extend(policy.get("resources", []))
    assert "camera/detections" in all_resources

def test_recipe_grants_local_pubsub_publish_to_camera_images():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    pubsub = ac.get("aws.greengrass.ipc.pubsub", {})
    all_resources = []
    for policy in pubsub.values():
        all_resources.extend(policy.get("resources", []))
    assert "camera/images" in all_resources

def test_recipe_grants_shadow_get_and_update_for_kvs_config():
    r = load_recipe()
    ac = r["ComponentConfiguration"]["DefaultConfiguration"]["accessControl"]
    shadow = ac.get("aws.greengrass.ShadowManager", {})
    all_ops = []
    all_resources = []
    for policy in shadow.values():
        all_ops.extend(policy.get("operations", []))
        all_resources.extend(policy.get("resources", []))
    assert "aws.greengrass#GetThingShadow" in all_ops
    assert "aws.greengrass#UpdateThingShadow" in all_ops
    assert any("kvs-config" in r for r in all_resources)
