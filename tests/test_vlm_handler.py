"""Unit tests for VlmHandler mode switching, CV triggers, and alert rules."""

import sys
import os
import json
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(__file__), '..', 'greengrass-components', 'artifacts',
    'com.example.VlmInferenceHandler', '1.0.0'
))

mock_clientv2 = MagicMock()
sys.modules['awsiot'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc'] = MagicMock()
sys.modules['awsiot.greengrasscoreipc.clientv2'] = mock_clientv2
sys.modules['requests'] = MagicMock()

import requests


@pytest.fixture
def mock_ipc_client():
    mock = MagicMock()
    return mock


@pytest.fixture
def handler(mock_ipc_client):
    mock_clientv2.GreengrassCoreIPCClientV2.return_value = mock_ipc_client
    with patch.dict(os.environ, {
        'AWS_IOT_THING_NAME': 'test-thing',
        'VLM_ENDPOINT': 'http://localhost:9090/v3/chat/completions',
    }):
        with patch('vlm_handler.CloudShadowClient') as mock_shadow:
            mock_shadow.return_value.get_shadow.return_value = {'state': {'reported': {}, 'desired': {}}}
            from vlm_handler import VlmHandler
            h = VlmHandler()
            h.ipc_client = mock_ipc_client
            yield h


class TestModeConfig:
    def test_default_mode_is_continuous(self, handler):
        assert handler.mode == 'continuous'

    def test_default_trigger_classes(self, handler):
        assert handler.trigger_classes == ['person']

    def test_default_trigger_cooldown(self, handler):
        assert handler.trigger_cooldown == 10

    def test_shadow_delta_updates_mode(self, handler):
        handler._apply_vlm_config({
            'mode': 'triggered',
            'trigger_classes': ['person', 'truck'],
            'trigger_cooldown': 15,
        })
        assert handler.mode == 'triggered'
        assert handler.trigger_classes == ['person', 'truck']
        assert handler.trigger_cooldown == 15


class TestTriggerLogic:
    def test_should_trigger_matches_class(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person', 'truck']
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is True

    def test_should_trigger_no_match(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        detections = [{'label': 'car', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is False

    def test_should_trigger_respects_cooldown(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        handler.trigger_cooldown = 10
        handler._last_trigger_time = time.time() - 5  # 5s ago, within cooldown
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is False

    def test_should_trigger_after_cooldown_expires(self, handler):
        handler.mode = 'triggered'
        handler.trigger_classes = ['person']
        handler.trigger_cooldown = 10
        handler._last_trigger_time = time.time() - 15  # 15s ago, past cooldown
        detections = [{'label': 'person', 'score': 0.9, 'box': {}}]
        assert handler._should_trigger(detections) is True


class TestAlertRules:
    def test_build_system_prompt_without_rules(self, handler):
        handler.system_prompt = 'You are a safety analyst.'
        handler.alert_rules = []
        result = handler._build_system_prompt()
        assert result == 'You are a safety analyst.'

    def test_build_system_prompt_with_rules(self, handler):
        handler.system_prompt = 'You are a safety analyst.'
        handler.alert_rules = ['Alert if no hard hat', 'Alert if in trench']
        result = handler._build_system_prompt()
        assert 'Alert if no hard hat' in result
        assert 'Alert if in trench' in result
        assert '"alerts"' in result

    def test_parse_response_with_alerts(self, handler):
        raw = json.dumps({
            'risk_level': 'HIGH',
            'summary': 'Unsafe scene',
            'risks': [],
            'alerts': [{'rule': 'No hard hat', 'triggered': True, 'detail': 'Worker without PPE'}]
        })
        result = handler._parse_response(raw)
        assert result['alerts'][0]['rule'] == 'No hard hat'

    def test_parse_response_without_alerts(self, handler):
        raw = json.dumps({
            'risk_level': 'LOW',
            'summary': 'Safe scene',
            'risks': []
        })
        result = handler._parse_response(raw)
        assert result.get('alerts', []) == []
