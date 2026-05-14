"""
Preservation Property Tests - Non-Delta Inference Behavior

**Validates: Requirements 3.1, 3.2, 3.3, 3.4, 3.5**

These property-based tests establish the baseline behavior that MUST remain unchanged
after the bug fix is applied. They verify:
- Delta messages without confidence_threshold leave config unchanged
- Delta messages with invalid/non-numeric confidence_threshold do not crash and leave config unchanged
- load_shadow_config() restores threshold from shadow reported state
- load_config() reads CONFIDENCE_THRESHOLD environment variable as initial default

EXPECTED OUTCOME: All tests PASS on UNFIXED code (confirms baseline behavior to preserve).
"""

import sys
import os
import json
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

from hypothesis import given, settings, assume
from hypothesis.strategies import (
    floats, integers, text, dictionaries, one_of,
    none, booleans, lists, just, sampled_from, composite
)


def make_shadow_delta_event(delta_dict):
    """Create a mock SubscriptionResponseMessage with the given delta dict."""
    event = MagicMock()
    event.json_message.message = delta_dict
    return event


def create_handler_instance(confidence_threshold=0.5):
    """Create an InferenceHandler instance with mocked dependencies."""
    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'ARTIFACT_PATH': '/tmp',
        'CONFIDENCE_THRESHOLD': str(confidence_threshold),
    }):
        import inference_handler_core
        with patch.object(inference_handler_core.clientv2, 'GreengrassCoreIPCClientV2', return_value=MagicMock()):
            with patch('builtins.open', MagicMock(return_value=MagicMock(
                __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value="person\ncar\ndog"))),
                __exit__=MagicMock(return_value=False)
            ))):
                # Patch load_shadow_config to avoid real shadow reads during init
                original_load_shadow = inference_handler_core.InferenceHandler.load_shadow_config
                inference_handler_core.InferenceHandler.load_shadow_config = lambda self: None
                try:
                    handler = inference_handler_core.InferenceHandler()
                finally:
                    inference_handler_core.InferenceHandler.load_shadow_config = original_load_shadow
    return handler


# Strategy: generate keys that are NOT 'confidence_threshold'
@composite
def non_threshold_keys(draw):
    """Generate dictionary keys that are not 'confidence_threshold'."""
    key = draw(text(min_size=1, max_size=30))
    assume(key != 'confidence_threshold')
    return key


# Strategy: generate values for non-threshold state entries
non_threshold_values = one_of(
    text(min_size=0, max_size=50),
    integers(min_value=-1000, max_value=1000),
    floats(min_value=-100, max_value=100, allow_nan=False, allow_infinity=False),
    booleans(),
)


# Strategy: generate non-numeric values that would fail float() conversion
# Note: Python's float(True) == 1.0 and float(False) == 0.0, so booleans are
# actually numeric. We only include values that truly fail float() conversion.
non_numeric_values = one_of(
    text(min_size=1, max_size=20).filter(lambda s: not _is_numeric(s)),
    just(None),
    just([1, 2, 3]),
    just({"nested": "dict"}),
)


def _is_numeric(s):
    """Check if a string can be converted to float."""
    try:
        float(s)
        return True
    except (ValueError, TypeError):
        return False


# =============================================================================
# Property 2a: Delta messages without confidence_threshold leave config unchanged
# =============================================================================

@given(
    other_key=non_threshold_keys(),
    other_value=non_threshold_values,
    version=integers(min_value=1, max_value=10000),
    timestamp=integers(min_value=1000000000, max_value=2000000000),
)
@settings(max_examples=50, deadline=None)
def test_preservation_non_threshold_delta_leaves_config_unchanged(
    other_key, other_value, version, timestamp
):
    """
    Property 2a: For all delta messages where confidence_threshold is absent from
    both top-level and state, config remains unchanged.

    **Validates: Requirements 3.1, 3.2**

    On UNFIXED code: the handler checks 'confidence_threshold' in delta (top-level).
    Since it's absent, config stays unchanged. This behavior must be preserved.
    """
    # Construct a delta message WITHOUT confidence_threshold anywhere
    delta_message = {
        "version": version,
        "timestamp": timestamp,
        "state": {
            other_key: other_value
        },
        "metadata": {}
    }

    # Verify confidence_threshold is absent from both top-level and state
    assert 'confidence_threshold' not in delta_message
    assert 'confidence_threshold' not in delta_message['state']

    # Create handler with known initial threshold
    handler = create_handler_instance(confidence_threshold=0.5)
    initial_threshold = handler.config['confidence_threshold']

    # Call on_shadow_delta
    event = make_shadow_delta_event(delta_message)
    handler.on_shadow_delta(event)

    # Config must remain unchanged
    assert handler.config['confidence_threshold'] == initial_threshold, (
        f"Expected config['confidence_threshold'] to remain {initial_threshold}, "
        f"but got {handler.config['confidence_threshold']}. "
        f"Delta without confidence_threshold should not modify config."
    )


# =============================================================================
# Property 2b: Non-numeric confidence_threshold values do not crash, config unchanged
# =============================================================================

@given(
    invalid_value=non_numeric_values,
    version=integers(min_value=1, max_value=10000),
    timestamp=integers(min_value=1000000000, max_value=2000000000),
)
@settings(max_examples=50, deadline=None)
def test_preservation_invalid_threshold_no_crash_config_unchanged(
    invalid_value, version, timestamp
):
    """
    Property 2b: For all delta messages with non-numeric confidence_threshold values,
    handler does not crash and config remains unchanged.

    **Validates: Requirements 3.5**

    On UNFIXED code: the handler checks 'confidence_threshold' in delta (top-level).
    When the value is at top level with an invalid type, float() raises an exception
    caught by the try/except. When nested under state, the key isn't found at top level
    so the handler skips it entirely. Either way, no crash and config unchanged.
    """
    # Test with confidence_threshold at TOP LEVEL (where unfixed code looks)
    # This exercises the existing error handling path
    delta_message_top_level = {
        "version": version,
        "timestamp": timestamp,
        "confidence_threshold": invalid_value,
        "state": {},
        "metadata": {}
    }

    handler = create_handler_instance(confidence_threshold=0.5)
    initial_threshold = handler.config['confidence_threshold']

    # Should not raise any exception
    event = make_shadow_delta_event(delta_message_top_level)
    handler.on_shadow_delta(event)

    # Config must remain unchanged (float() conversion fails, exception caught)
    assert handler.config['confidence_threshold'] == initial_threshold, (
        f"Expected config['confidence_threshold'] to remain {initial_threshold}, "
        f"but got {handler.config['confidence_threshold']}. "
        f"Invalid threshold value should not modify config."
    )


@given(
    invalid_value=non_numeric_values,
    version=integers(min_value=1, max_value=10000),
    timestamp=integers(min_value=1000000000, max_value=2000000000),
)
@settings(max_examples=50, deadline=None)
def test_preservation_invalid_threshold_nested_no_crash(
    invalid_value, version, timestamp
):
    """
    Property 2b (nested): For all delta messages with non-numeric confidence_threshold
    nested under state, handler does not crash and config remains unchanged.

    **Validates: Requirements 3.5**

    On UNFIXED code: the handler checks 'confidence_threshold' in delta (top-level).
    Since it's only under state, the handler skips it. No crash, config unchanged.
    """
    delta_message_nested = {
        "version": version,
        "timestamp": timestamp,
        "state": {
            "confidence_threshold": invalid_value
        },
        "metadata": {}
    }

    # Verify confidence_threshold is NOT at top level (only under state)
    assert 'confidence_threshold' not in delta_message_nested
    assert 'confidence_threshold' in delta_message_nested['state']

    handler = create_handler_instance(confidence_threshold=0.5)
    initial_threshold = handler.config['confidence_threshold']

    # Should not raise any exception
    event = make_shadow_delta_event(delta_message_nested)
    handler.on_shadow_delta(event)

    # Config must remain unchanged
    assert handler.config['confidence_threshold'] == initial_threshold, (
        f"Expected config['confidence_threshold'] to remain {initial_threshold}, "
        f"but got {handler.config['confidence_threshold']}. "
        f"Invalid nested threshold value should not modify config."
    )


# =============================================================================
# Property 2c: load_shadow_config() restores threshold from shadow reported state
# =============================================================================

@given(
    shadow_threshold=floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, deadline=None)
def test_preservation_load_shadow_config_restores_threshold(shadow_threshold):
    """
    Property 2c: For all valid startup configurations, load_shadow_config()
    restores threshold from shadow['state']['reported']['confidence_threshold'].

    **Validates: Requirements 3.1**

    On UNFIXED code: load_shadow_config reads from shadow reported state correctly.
    This behavior must be preserved after the fix.
    """
    import inference_handler_core

    # Create handler without shadow loading
    handler = create_handler_instance(confidence_threshold=0.5)

    # Mock the IPC client to return a shadow with the given threshold
    shadow_payload = json.dumps({
        "state": {
            "reported": {
                "confidence_threshold": shadow_threshold
            }
        }
    }).encode('utf-8')

    mock_response = MagicMock()
    mock_response.payload = shadow_payload
    handler.ipc_client.get_thing_shadow = MagicMock(return_value=mock_response)
    handler.thing_name = 'test-thing'

    # Call load_shadow_config
    handler.load_shadow_config()

    # Threshold should be restored from shadow
    assert abs(handler.config['confidence_threshold'] - shadow_threshold) < 1e-10, (
        f"Expected config['confidence_threshold'] to be {shadow_threshold} "
        f"(from shadow reported state), but got {handler.config['confidence_threshold']}."
    )


# =============================================================================
# Property 2d: load_config() reads CONFIDENCE_THRESHOLD env var as initial default
# =============================================================================

@given(
    env_threshold=floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, deadline=None)
def test_preservation_load_config_reads_env_var(env_threshold):
    """
    Property 2d: For all valid startup configurations, load_config() reads
    CONFIDENCE_THRESHOLD environment variable as initial default.

    **Validates: Requirements 3.2**

    On UNFIXED code: load_config reads the env var and converts to float.
    This behavior must be preserved after the fix.
    """
    import inference_handler_core

    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'ARTIFACT_PATH': '/tmp',
        'CONFIDENCE_THRESHOLD': str(env_threshold),
    }):
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

    # Threshold should match the env var value
    assert abs(handler.config['confidence_threshold'] - env_threshold) < 1e-10, (
        f"Expected config['confidence_threshold'] to be {env_threshold} "
        f"(from CONFIDENCE_THRESHOLD env var), but got {handler.config['confidence_threshold']}."
    )
