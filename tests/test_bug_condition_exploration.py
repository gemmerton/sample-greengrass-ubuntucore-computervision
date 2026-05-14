"""
Bug Condition Exploration Test - Shadow Delta Threshold Extraction Failure

**Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3**

This property-based test encodes the EXPECTED behavior for on_shadow_delta:
- When a shadow delta message arrives with confidence_threshold nested under 'state',
  the handler should extract the value, update config, and call update_shadow_reported().

EXPECTED OUTCOME on UNFIXED code: This test FAILS.
- config['confidence_threshold'] remains at startup value 0.5
- update_shadow_reported() is never called
- This proves the bug exists: the handler checks the wrong nesting level.

Bug condition from design:
  isBugCondition(input) returns True when:
    'state' IN input AND
    'confidence_threshold' IN input['state'] AND
    'confidence_threshold' NOT IN input (top-level)
"""

import sys
import os
from unittest.mock import MagicMock, patch

# Mock all external dependencies BEFORE importing the module under test
mock_modules = {
    'ovmsclient': MagicMock(),
    'cv2': MagicMock(),
    'boto3': MagicMock(),
    'awsiot': MagicMock(),
    'awsiot.greengrasscoreipc': MagicMock(),
    'awsiot.greengrasscoreipc.clientv2': MagicMock(),
    'awsiot.greengrasscoreipc.model': MagicMock(),
}

for mod_name, mock_mod in mock_modules.items():
    sys.modules.setdefault(mod_name, mock_mod)

# Add the source directory to path
sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.InferenceHandlerCore', '1.0.0'
))

from hypothesis import given, settings
from hypothesis.strategies import floats, integers


def make_shadow_delta_event(delta_dict):
    """Create a mock SubscriptionResponseMessage with the given delta dict."""
    event = MagicMock()
    event.json_message.message = delta_dict
    return event


def create_handler_instance():
    """Create an InferenceHandler instance with mocked dependencies for testing on_shadow_delta."""
    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'ARTIFACT_PATH': '/tmp',
        'CONFIDENCE_THRESHOLD': '0.5',
    }):
        # Import here so mocked sys.modules are in effect
        import inference_handler_core
        # Patch the IPC client and file open used during __init__
        with patch.object(inference_handler_core.clientv2, 'GreengrassCoreIPCClientV2', return_value=MagicMock()):
            with patch('builtins.open', MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="person\ncar\ndog"))),
                __exit__=MagicMock(return_value=False)
            ))):
                # Patch load_shadow_config to avoid real shadow reads
                original_load_shadow = inference_handler_core.InferenceHandler.load_shadow_config
                inference_handler_core.InferenceHandler.load_shadow_config = lambda self: None
                try:
                    handler = inference_handler_core.InferenceHandler()
                finally:
                    inference_handler_core.InferenceHandler.load_shadow_config = original_load_shadow
    return handler


@given(
    threshold=floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    version=integers(min_value=1, max_value=10000),
    timestamp=integers(min_value=1000000000, max_value=2000000000),
)
@settings(max_examples=50, deadline=None)
def test_bug_condition_shadow_delta_threshold_extraction(threshold, version, timestamp):
    """
    Property 1: Bug Condition - Shadow Delta Threshold Extraction Failure

    **Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3**

    For any shadow delta message where confidence_threshold is nested under 'state'
    (the standard AWS IoT Core format), after calling on_shadow_delta(event):
    - self.config['confidence_threshold'] should equal the threshold value
    - update_shadow_reported() should have been called

    Bug condition: 'state' IN input AND 'confidence_threshold' IN input['state']
                   AND 'confidence_threshold' NOT IN input (top-level)
    """
    # Construct a shadow delta message in the standard AWS IoT Core format
    delta_message = {
        "version": version,
        "timestamp": timestamp,
        "state": {
            "confidence_threshold": threshold
        },
        "metadata": {
            "confidence_threshold": {
                "timestamp": timestamp
            }
        }
    }

    # Verify bug condition holds: confidence_threshold is under state, NOT at top level
    assert 'state' in delta_message
    assert 'confidence_threshold' in delta_message['state']
    assert 'confidence_threshold' not in delta_message  # not at top level

    # Create handler with default config (threshold = 0.5)
    handler = create_handler_instance()
    initial_threshold = handler.config['confidence_threshold']
    assert initial_threshold == 0.5, f"Expected initial threshold 0.5, got {initial_threshold}"

    # Mock update_shadow_reported to track if it's called
    handler.update_shadow_reported = MagicMock()

    # Create the event and call on_shadow_delta
    event = make_shadow_delta_event(delta_message)
    handler.on_shadow_delta(event)

    # Property assertions (expected behavior):
    # 1. Config should be updated to the new threshold value
    assert handler.config['confidence_threshold'] == threshold, (
        f"Expected config['confidence_threshold'] to be {threshold}, "
        f"but got {handler.config['confidence_threshold']}. "
        f"The handler failed to extract the threshold from delta['state']['confidence_threshold']. "
        f"Bug confirmed: handler checks wrong nesting level."
    )

    # 2. update_shadow_reported() should have been called
    assert handler.update_shadow_reported.called, (
        "Expected update_shadow_reported() to be called after threshold update, "
        "but it was never called. Bug confirmed: handler never reaches the update branch."
    )
