/**
 * Tests for iotShadowService model-config methods
 *
 * Validates: Requirements 1.1, 1.2, 1.4, 1.5, 4.1
 */

import { describe, test, expect, vi, beforeEach } from 'vitest';

const mockSend = vi.fn();

vi.mock('@aws-sdk/client-iot-data-plane', () => {
  return {
    IoTDataPlaneClient: vi.fn().mockImplementation(() => ({
      send: mockSend,
    })),
    GetThingShadowCommand: vi.fn().mockImplementation((input) => ({
      ...input,
      _commandName: 'GetThingShadowCommand',
    })),
    UpdateThingShadowCommand: vi.fn().mockImplementation((input) => ({
      ...input,
      _commandName: 'UpdateThingShadowCommand',
    })),
  };
});

import { IotShadowService, parseModelConfigShadow } from '../iotShadowService';
import { UpdateThingShadowCommand } from '@aws-sdk/client-iot-data-plane';

function encodeShadowPayload(obj: any): Uint8Array {
  return new TextEncoder().encode(JSON.stringify(obj));
}

describe('iotShadowService - model-config methods', () => {
  let service: IotShadowService;
  const mockCredentials = { accessKeyId: 'test', secretAccessKey: 'test' };
  const mockRegion = 'us-east-1';
  const mockThingName = 'test-device';

  beforeEach(() => {
    service = new IotShadowService();
    vi.clearAllMocks();
  });

  describe('getModelConfigShadow', () => {
    test('returns parsed state for valid shadow', async () => {
      const shadowPayload = {
        state: {
          reported: {
            active_model: 'faster-rcnn',
            models: {
              'faster-rcnn': {
                status: 'ready',
                model_metadata: {
                  model_name: 'faster_rcnn',
                  version: '1.0.0',
                  input_shape: [1, 255, 255, 3],
                  local_path: '/snap/ovms-engine/components/model-faster-rcnn/',
                },
              },
              efficientnet: {
                status: 'installing',
                model_metadata: {
                  model_name: 'efficientnet',
                  version: '2.0.0',
                  input_shape: [1, 224, 224, 3],
                  local_path: '/snap/ovms-engine/components/model-efficientnet/',
                },
              },
            },
          },
        },
      };

      mockSend.mockResolvedValueOnce({
        payload: encodeShadowPayload(shadowPayload),
      });

      const result = await service.getModelConfigShadow(mockThingName, mockCredentials, mockRegion);

      expect(result).not.toBeNull();
      expect(result!.reported_active_model).toBe('faster-rcnn');
      expect(Object.keys(result!.reported_models)).toHaveLength(2);
      expect(result!.reported_models['faster-rcnn'].status).toBe('ready');
      expect(result!.reported_models['faster-rcnn'].model_metadata.model_name).toBe('faster_rcnn');
      expect(result!.reported_models['faster-rcnn'].model_metadata.version).toBe('1.0.0');
      expect(result!.reported_models['faster-rcnn'].model_metadata.input_shape).toEqual([1, 255, 255, 3]);
      expect(result!.reported_models['efficientnet'].status).toBe('installing');
    });

    test('returns null for ResourceNotFoundException', async () => {
      const error = new Error('Shadow not found');
      error.name = 'ResourceNotFoundException';
      mockSend.mockRejectedValueOnce(error);

      const result = await service.getModelConfigShadow(mockThingName, mockCredentials, mockRegion);

      expect(result).toBeNull();
    });

    test('throws on network/permission errors', async () => {
      const networkError = new Error('Network timeout');
      networkError.name = 'TimeoutError';
      mockSend.mockRejectedValueOnce(networkError);

      await expect(
        service.getModelConfigShadow(mockThingName, mockCredentials, mockRegion),
      ).rejects.toThrow('Network timeout');

      const permissionError = new Error('Access denied');
      permissionError.name = 'UnauthorizedException';
      mockSend.mockRejectedValueOnce(permissionError);

      await expect(
        service.getModelConfigShadow(mockThingName, mockCredentials, mockRegion),
      ).rejects.toThrow('Access denied');
    });
  });

  describe('parseModelConfigShadow', () => {
    test('handles missing fields with defaults', () => {
      const payload = {
        state: {
          reported: {
            active_model: 'my-model',
            models: {
              'my-model': {
                status: 'ready',
                // model_metadata is entirely missing
              },
            },
          },
        },
      };

      const result = parseModelConfigShadow(payload);

      expect(result.reported_active_model).toBe('my-model');
      expect(result.reported_models['my-model'].status).toBe('ready');
      // Defaults applied for missing model_metadata fields
      expect(result.reported_models['my-model'].model_metadata.model_name).toBe('my-model');
      expect(result.reported_models['my-model'].model_metadata.version).toBe('unknown');
      expect(result.reported_models['my-model'].model_metadata.input_shape).toEqual([]);
      expect(result.reported_models['my-model'].model_metadata.local_path).toBe('');
    });

    test('handles completely missing state.reported', () => {
      const payload = {};

      const result = parseModelConfigShadow(payload);

      expect(result.reported_active_model).toBeNull();
      expect(result.reported_models).toEqual({});
    });

    test('handles missing models map', () => {
      const payload = {
        state: {
          reported: {
            active_model: 'some-model',
          },
        },
      };

      const result = parseModelConfigShadow(payload);

      expect(result.reported_active_model).toBe('some-model');
      expect(result.reported_models).toEqual({});
    });

    test('normalizes null active_model to null', () => {
      const payload = {
        state: {
          reported: {
            active_model: null,
            models: {},
          },
        },
      };

      const result = parseModelConfigShadow(payload);
      expect(result.reported_active_model).toBeNull();
    });

    test('normalizes empty string active_model to null', () => {
      const payload = {
        state: {
          reported: {
            active_model: '',
            models: {},
          },
        },
      };

      const result = parseModelConfigShadow(payload);
      expect(result.reported_active_model).toBeNull();
    });

    test('normalizes whitespace-only active_model to null', () => {
      const payload = {
        state: {
          reported: {
            active_model: '   ',
            models: {},
          },
        },
      };

      const result = parseModelConfigShadow(payload);
      expect(result.reported_active_model).toBeNull();
    });

    test('normalizes undefined active_model to null', () => {
      const payload = {
        state: {
          reported: {
            models: {},
          },
        },
      };

      const result = parseModelConfigShadow(payload);
      expect(result.reported_active_model).toBeNull();
    });

    test('defaults invalid status values to failed', () => {
      const payload = {
        state: {
          reported: {
            active_model: null,
            models: {
              'model-a': {
                status: 'unknown-status',
                model_metadata: {
                  model_name: 'Model A',
                  version: '1.0.0',
                  input_shape: [1, 224, 224, 3],
                  local_path: '/path/a',
                },
              },
              'model-b': {
                status: 123,
                model_metadata: {
                  model_name: 'Model B',
                  version: '2.0.0',
                  input_shape: [1, 300, 300, 3],
                  local_path: '/path/b',
                },
              },
            },
          },
        },
      };

      const result = parseModelConfigShadow(payload);

      expect(result.reported_models['model-a'].status).toBe('failed');
      expect(result.reported_models['model-b'].status).toBe('failed');
    });
  });

  describe('setActiveModel', () => {
    test('constructs correct payload structure', async () => {
      mockSend.mockResolvedValueOnce({});

      await service.setActiveModel(mockThingName, mockCredentials, mockRegion, 'efficientnet');

      // Verify UpdateThingShadowCommand was called
      expect(UpdateThingShadowCommand).toHaveBeenCalledTimes(1);

      // Verify the arguments passed to the command constructor
      const callArgs = vi.mocked(UpdateThingShadowCommand).mock.calls[0][0];
      expect(callArgs.thingName).toBe(mockThingName);
      expect(callArgs.shadowName).toBe('model-config');

      // Verify the payload content
      const payloadStr = new TextDecoder().decode(callArgs.payload as Uint8Array);
      const payloadObj = JSON.parse(payloadStr);

      expect(payloadObj).toEqual({
        state: {
          desired: {
            active_model: 'efficientnet',
          },
        },
      });
    });

    test('throws on API failure with descriptive error', async () => {
      const apiError = new Error('Service unavailable');
      mockSend.mockRejectedValueOnce(apiError);

      await expect(
        service.setActiveModel(mockThingName, mockCredentials, mockRegion, 'my-model'),
      ).rejects.toThrow(
        "Failed to set active model 'my-model' for thing 'test-device': Service unavailable",
      );
    });
  });
});
