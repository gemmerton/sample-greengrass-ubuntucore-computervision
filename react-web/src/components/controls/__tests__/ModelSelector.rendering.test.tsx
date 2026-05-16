/**
 * ModelSelector Component Rendering Tests
 *
 * Tests the rendering behavior of the ModelSelector component under various
 * data states: empty thingName, null credentials, null shadow, empty models,
 * populated models with various statuses, and edge cases.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { ModelSelector } from '../ModelSelector';
import { ModelConfigShadowState } from '../../../types/modelConfig';

// Mock the iotShadowService
vi.mock('../../../services/iotShadowService', () => ({
  iotShadowService: {
    getModelConfigShadow: vi.fn(),
    setActiveModel: vi.fn(),
  },
}));

// Mock the useAuthenticatedAWS hook
vi.mock('../../../hooks/useAuthenticatedAWS', () => ({
  useAuthenticatedAWS: vi.fn(),
}));

import { iotShadowService } from '../../../services/iotShadowService';
import { useAuthenticatedAWS } from '../../../hooks/useAuthenticatedAWS';

const mockGetModelConfigShadow = iotShadowService.getModelConfigShadow as ReturnType<typeof vi.fn>;
const mockUseAuthenticatedAWS = useAuthenticatedAWS as ReturnType<typeof vi.fn>;

const defaultCredentials = { accessKeyId: 'test', secretAccessKey: 'test' };
const defaultRegion = 'us-east-1';

describe('ModelSelector Rendering', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Default: authenticated with credentials
    mockUseAuthenticatedAWS.mockReturnValue({
      credentials: defaultCredentials,
      isAuthenticated: true,
      region: defaultRegion,
    });
  });

  describe('Pre-condition states', () => {
    test('renders Thing Name required hint when thingName is empty', () => {
      render(<ModelSelector thingName="" />);

      expect(
        screen.getByText(/Set an IoT Thing Name above to enable model selection/i)
      ).toBeInTheDocument();
    });

    test('renders authentication required message when credentials are null', () => {
      mockUseAuthenticatedAWS.mockReturnValue({
        credentials: null,
        isAuthenticated: false,
        region: defaultRegion,
      });

      render(<ModelSelector thingName="my-thing" />);

      expect(
        screen.getByText(/Authentication required to manage model selection/i)
      ).toBeInTheDocument();
    });
  });

  describe('Shadow response states', () => {
    test('renders "no model configuration" when shadow returns null', async () => {
      mockGetModelConfigShadow.mockResolvedValue(null);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        expect(
          screen.getByText(/No model configuration available/i)
        ).toBeInTheDocument();
      });
    });

    test('renders "no models installed" when models map is empty', async () => {
      const emptyState: ModelConfigShadowState = {
        reported_active_model: null,
        reported_models: {},
      };
      mockGetModelConfigShadow.mockResolvedValue(emptyState);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        expect(
          screen.getByText(/No models installed on device/i)
        ).toBeInTheDocument();
      });
    });
  });

  describe('Model inventory display', () => {
    test('renders all models with correct name, ID, version, and status', async () => {
      const state: ModelConfigShadowState = {
        reported_active_model: null,
        reported_models: {
          'faster-rcnn': {
            status: 'ready',
            model_metadata: {
              model_name: 'Faster RCNN',
              version: '1.0.0',
              input_shape: [1, 255, 255, 3],
              local_path: '/models/faster-rcnn',
            },
          },
          'efficientnet': {
            status: 'installing',
            model_metadata: {
              model_name: 'EfficientNet',
              version: '2.0.0',
              input_shape: [1, 224, 224, 3],
              local_path: '/models/efficientnet',
            },
          },
          'custom-ppe': {
            status: 'failed',
            model_metadata: {
              model_name: 'Custom PPE',
              version: '1.0.0',
              input_shape: [1, 300, 300, 3],
              local_path: '/models/custom-ppe',
            },
            failure_reason: 'OVMS failed to load model',
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(state);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        // Model names
        expect(screen.getByText('Faster RCNN')).toBeInTheDocument();
        expect(screen.getByText('EfficientNet')).toBeInTheDocument();
        expect(screen.getByText('Custom PPE')).toBeInTheDocument();
      });

      // Model IDs and versions (rendered as "modelId · vX.X.X")
      // Use getAllByText for version since multiple models can share the same version
      expect(screen.getByText(/faster-rcnn/)).toBeInTheDocument();
      expect(screen.getByText(/efficientnet/)).toBeInTheDocument();
      expect(screen.getByText(/custom-ppe/)).toBeInTheDocument();
      // Two models have v1.0.0 (faster-rcnn and custom-ppe)
      expect(screen.getAllByText(/v1\.0\.0/)).toHaveLength(2);
      expect(screen.getByText(/v2\.0\.0/)).toBeInTheDocument();

      // Status badges
      expect(screen.getByText('Ready')).toBeInTheDocument();
      expect(screen.getByText('Installing')).toBeInTheDocument();
      expect(screen.getByText('Failed')).toBeInTheDocument();
    });

    test('active model has distinct visual marker (Active badge)', async () => {
      const state: ModelConfigShadowState = {
        reported_active_model: 'faster-rcnn',
        reported_models: {
          'faster-rcnn': {
            status: 'ready',
            model_metadata: {
              model_name: 'Faster RCNN',
              version: '1.0.0',
              input_shape: [1, 255, 255, 3],
              local_path: '/models/faster-rcnn',
            },
          },
          'efficientnet': {
            status: 'ready',
            model_metadata: {
              model_name: 'EfficientNet',
              version: '2.0.0',
              input_shape: [1, 224, 224, 3],
              local_path: '/models/efficientnet',
            },
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(state);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        expect(screen.getByText('Active')).toBeInTheDocument();
      });

      // The active badge should be present exactly once (for faster-rcnn)
      const activeBadges = screen.getAllByText('Active');
      expect(activeBadges).toHaveLength(1);
    });

    test('active model not in inventory shows "not found" indicator', async () => {
      const state: ModelConfigShadowState = {
        reported_active_model: 'missing-model',
        reported_models: {
          'faster-rcnn': {
            status: 'ready',
            model_metadata: {
              model_name: 'Faster RCNN',
              version: '1.0.0',
              input_shape: [1, 255, 255, 3],
              local_path: '/models/faster-rcnn',
            },
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(state);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        expect(
          screen.getByText(/Model not found in inventory/i)
        ).toBeInTheDocument();
      });

      // The missing model ID should be displayed
      expect(screen.getByText('missing-model')).toBeInTheDocument();
      // It should still show the Active badge for the not-found model
      expect(screen.getByText('Active')).toBeInTheDocument();
    });

    test('failed model displays failure reason', async () => {
      const state: ModelConfigShadowState = {
        reported_active_model: null,
        reported_models: {
          'broken-model': {
            status: 'failed',
            model_metadata: {
              model_name: 'Broken Model',
              version: '1.0.0',
              input_shape: [1, 300, 300, 3],
              local_path: '/models/broken',
            },
            failure_reason: 'OVMS failed to load model within 60 seconds',
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(state);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        expect(
          screen.getByText('OVMS failed to load model within 60 seconds')
        ).toBeInTheDocument();
      });
    });

    test('failed model without failure reason shows generic "Failed" message', async () => {
      const state: ModelConfigShadowState = {
        reported_active_model: null,
        reported_models: {
          'broken-model': {
            status: 'failed',
            model_metadata: {
              model_name: 'Broken Model',
              version: '1.0.0',
              input_shape: [1, 300, 300, 3],
              local_path: '/models/broken',
            },
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(state);

      render(<ModelSelector thingName="my-thing" />);

      await waitFor(() => {
        // The component renders "Failed" as the inline failure text when no reason is provided
        const failureElements = screen.getAllByText('Failed');
        // At least one "Failed" text should be the inline failure message (not just the badge)
        expect(failureElements.length).toBeGreaterThanOrEqual(1);
      });

      // Verify the generic "Failed" text is shown in the item failure span
      const failureSpan = document.querySelector('.model-selector__item-failure');
      expect(failureSpan).toBeInTheDocument();
      expect(failureSpan?.textContent).toBe('Failed');
    });
  });
});
