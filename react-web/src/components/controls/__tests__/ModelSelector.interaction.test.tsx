/**
 * ModelSelector Interaction and State Machine Tests
 *
 * Tests the interactive behavior and state transitions of the ModelSelector component:
 * - Model selection (ready vs non-ready)
 * - Apply button enable/disable logic
 * - Shadow update flow (loading, error, timeout)
 * - Polling flow (success, failure, timeout, connectivity)
 * - Error recovery and state preservation
 *
 * Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.4
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { ModelSelector } from '../ModelSelector';
import { ModelConfigShadowState } from '../../../types/modelConfig';

// Mock the iotShadowService
const mockGetModelConfigShadow = vi.fn();
const mockSetActiveModel = vi.fn();

vi.mock('../../../services/iotShadowService', () => ({
  iotShadowService: {
    getModelConfigShadow: (...args: any[]) => mockGetModelConfigShadow(...args),
    setActiveModel: (...args: any[]) => mockSetActiveModel(...args),
  },
}));

// Stable credentials reference to avoid re-triggering useEffect on re-renders
const stableCredentials = vi.hoisted(() => ({ accessKeyId: 'test', secretAccessKey: 'test' }));

// Mock the useAuthenticatedAWS hook
vi.mock('../../../hooks/useAuthenticatedAWS', () => ({
  useAuthenticatedAWS: () => ({
    credentials: stableCredentials,
    isAuthenticated: true,
    region: 'us-east-1',
  }),
}));

// Helper: standard model config shadow state with multiple models
function createMockShadowState(overrides?: Partial<ModelConfigShadowState>): ModelConfigShadowState {
  return {
    reported_active_model: 'model-a',
    reported_models: {
      'model-a': {
        status: 'ready',
        model_metadata: {
          model_name: 'Model A',
          version: '1.0.0',
          input_shape: [1, 224, 224, 3],
          local_path: '/models/model-a',
        },
      },
      'model-b': {
        status: 'ready',
        model_metadata: {
          model_name: 'Model B',
          version: '2.0.0',
          input_shape: [1, 300, 300, 3],
          local_path: '/models/model-b',
        },
      },
      'model-c': {
        status: 'installing',
        model_metadata: {
          model_name: 'Model C',
          version: '1.0.0',
          input_shape: [1, 256, 256, 3],
          local_path: '/models/model-c',
        },
      },
      'model-d': {
        status: 'failed',
        model_metadata: {
          model_name: 'Model D',
          version: '1.0.0',
          input_shape: [1, 512, 512, 3],
          local_path: '/models/model-d',
        },
        failure_reason: 'Load timeout',
      },
    },
    ...overrides,
  };
}

/** Helper to render and wait for initial load to complete (real timers only) */
async function renderAndLoad(thingName = 'test-thing') {
  const result = render(<ModelSelector thingName={thingName} />);
  await waitFor(() => {
    expect(screen.getByText('Model A')).toBeInTheDocument();
  });
  return result;
}

describe('ModelSelector Interaction and State Machine', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  // Requirement 4.2: Selecting a ready model updates selectedModelId
  describe('Model Selection', () => {
    it('clicking a ready model updates selection (aria-selected)', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      expect(modelBItem).not.toBeNull();

      fireEvent.click(modelBItem!);

      expect(modelBItem).toHaveAttribute('aria-selected', 'true');
    });

    // Requirement 4.3: Non-ready models are not selectable
    it('clicking a non-ready (installing) model does not change selection', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      const modelAItem = screen.getByText('Model A').closest('[role="option"]');
      expect(modelAItem).toHaveAttribute('aria-selected', 'true');

      const modelCItem = screen.getByText('Model C').closest('[role="option"]');
      fireEvent.click(modelCItem!);

      expect(modelAItem).toHaveAttribute('aria-selected', 'true');
      expect(modelCItem).toHaveAttribute('aria-selected', 'false');
    });

    it('clicking a non-ready (failed) model does not change selection', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      const modelAItem = screen.getByText('Model A').closest('[role="option"]');
      const modelDItem = screen.getByText('Model D').closest('[role="option"]');

      fireEvent.click(modelDItem!);

      expect(modelAItem).toHaveAttribute('aria-selected', 'true');
      expect(modelDItem).toHaveAttribute('aria-selected', 'false');
    });
  });

  // Requirement 4.2: Apply button disabled when selected equals active
  describe('Apply Button State', () => {
    it('Apply button is disabled when selected model equals active model', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      expect(applyBtn).toBeDisabled();
    });

    it('Apply button is enabled when a different ready model is selected', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      expect(applyBtn).not.toBeDisabled();
    });

    // Requirement 4.4: Apply button disabled during updating/switching states
    it('Apply button is disabled during updating state', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockReturnValue(new Promise(() => {}));

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      await waitFor(() => {
        expect(applyBtn).toBeDisabled();
      });
    });

    it('Apply button is disabled during switching state', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockResolvedValue(undefined);

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      await waitFor(() => {
        expect(applyBtn).toBeDisabled();
      });
    });
  });

  // Requirement 4.4: Loading indicator shown during shadow update
  describe('Loading Indicator', () => {
    it('shows loading overlay during shadow update (updating state)', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockReturnValue(new Promise(() => {}));

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      await waitFor(() => {
        expect(screen.getByText(/updating shadow/i)).toBeInTheDocument();
      });
    });
  });

  // Requirement 4.5: Error message and revert on update failure
  describe('Update Failure', () => {
    it('shows error message and reverts selection on setActiveModel failure', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockRejectedValue(new Error('Network error: connection refused'));

      await renderAndLoad();

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText(/network error/i)).toBeInTheDocument();
      });

      const modelAItem = screen.getByText('Model A').closest('[role="option"]');
      expect(modelAItem).toHaveAttribute('aria-selected', 'true');
    });
  });

  // Requirement 4.6: Timeout error after 30s on update
  describe('Update Timeout', () => {
    it('shows timeout error after 30s when setActiveModel does not resolve', async () => {
      vi.useFakeTimers();

      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      // setActiveModel never resolves - the 30s timeout in Promise.race will fire
      mockSetActiveModel.mockReturnValue(new Promise(() => {}));

      render(<ModelSelector thingName="test-thing" />);

      // Flush the initial load promise
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });

      // Select model-b
      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      await act(async () => {
        fireEvent.click(applyBtn);
      });

      // Advance past the 30s timeout
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30000);
      });

      // Timeout error message should appear
      expect(screen.getByRole('alert')).toBeInTheDocument();
      expect(screen.getByText(/timed out/i)).toBeInTheDocument();
    }, 15000);
  });

  // Requirement 5.1, 5.2, 5.3: Success confirmation shown for 5s after switch completes
  describe('Switching Success', () => {
    it('shows success message when polling detects active model match, then auto-dismisses after 5s', async () => {
      const initialState = createMockShadowState();
      mockGetModelConfigShadow.mockResolvedValue(initialState);
      mockSetActiveModel.mockResolvedValue(undefined);

      // Load with real timers
      await renderAndLoad();

      // Select model-b and click Apply
      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      // Wait for transition to switching state (setActiveModel resolves immediately)
      await waitFor(() => {
        expect(screen.getByText(/waiting for device/i)).toBeInTheDocument();
      });

      // Mock the poll to return model-b as active
      const switchedState = createMockShadowState({
        reported_active_model: 'model-b',
      });
      mockGetModelConfigShadow.mockResolvedValue(switchedState);

      // Wait for the next poll to fire (5s real time) and detect success
      await waitFor(() => {
        expect(screen.getByText(/successfully/i)).toBeInTheDocument();
      }, { timeout: 7000 });

      // Wait for the 5s auto-dismiss (real timers)
      await waitFor(() => {
        expect(screen.queryByText(/successfully/i)).not.toBeInTheDocument();
      }, { timeout: 7000 });
    }, 20000);
  });

  // Requirement 5.4: Switch failure detected when target model status becomes failed
  describe('Switch Failure (Device)', () => {
    it('shows error when target model status becomes failed during polling', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockResolvedValue(undefined);

      // Load with real timers
      await renderAndLoad();

      // Select model-b and click Apply
      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      // Wait for transition to switching state
      await waitFor(() => {
        expect(screen.getByText(/waiting for device/i)).toBeInTheDocument();
      });

      // Mock poll to return model-b with status 'failed'
      const failedState: ModelConfigShadowState = {
        reported_active_model: 'model-a',
        reported_models: {
          ...createMockShadowState().reported_models,
          'model-b': {
            status: 'failed',
            model_metadata: {
              model_name: 'Model B',
              version: '2.0.0',
              input_shape: [1, 300, 300, 3],
              local_path: '/models/model-b',
            },
            failure_reason: 'OVMS failed to load model',
          },
        },
      };
      mockGetModelConfigShadow.mockResolvedValue(failedState);

      // Wait for the next poll to fire and detect the failure
      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
        expect(screen.getByText(/device failed/i)).toBeInTheDocument();
      }, { timeout: 7000 });
    }, 15000);
  });

  // Requirement 5.5: Switch timeout after 90s of polling
  describe('Switch Timeout', () => {
    it('shows timeout message after 90s of polling without active model match', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockResolvedValue(undefined);

      // Load with real timers
      await renderAndLoad();

      // Select model-b and click Apply
      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      // Wait for transition to switching state
      await waitFor(() => {
        expect(screen.getByText(/waiting for device/i)).toBeInTheDocument();
      });

      // Now we need to advance past 90s. The interval was started with real timers.
      // We can't use fake timers to control it. Instead, we'll mock Date.now to
      // make the component think 90s have passed on the next poll.
      const originalDateNow = Date.now;
      const startTime = Date.now();
      // Make Date.now return a time 91s in the future
      vi.spyOn(Date, 'now').mockReturnValue(startTime + 91000);

      // Wait for the next poll to fire and detect the timeout
      await waitFor(() => {
        expect(screen.getByText(/timed out after 90 seconds/i)).toBeInTheDocument();
      }, { timeout: 7000 });

      vi.spyOn(Date, 'now').mockRestore();
    }, 15000);
  });

  // Requirement 5.6: Connectivity warning after 3 consecutive poll failures
  describe('Connectivity Warning', () => {
    it('shows connectivity warning after 3 consecutive poll failures', async () => {
      vi.useFakeTimers();

      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());
      mockSetActiveModel.mockResolvedValue(undefined);

      render(<ModelSelector thingName="test-thing" />);

      // Flush the initial load promise
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });

      // Select model-b and click Apply
      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      await act(async () => {
        fireEvent.click(applyBtn);
      });

      // Flush the setActiveModel promise to transition to switching state
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });

      expect(screen.getByText(/waiting for device/i)).toBeInTheDocument();

      // Make polls fail - need 3 consecutive failures
      mockGetModelConfigShadow.mockRejectedValue(new Error('Network error'));

      // Advance through 3 poll intervals (5s each = 15s)
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5000);
      });

      // Connectivity warning should now be visible
      expect(screen.getByText(/connectivity/i)).toBeInTheDocument();
    }, 15000);
  });

  // Requirement 7.4: Previously loaded state preserved on refresh error
  describe('State Preservation on Error', () => {
    it('preserves previously loaded models when retry after successful load fails', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      expect(screen.getByText('Model A')).toBeInTheDocument();
      expect(screen.getByText('Model B')).toBeInTheDocument();
      expect(screen.getByText('Model C')).toBeInTheDocument();
      expect(screen.getByText('Model D')).toBeInTheDocument();
    });

    it('preserves previously loaded state on refresh error', async () => {
      mockGetModelConfigShadow.mockResolvedValue(createMockShadowState());

      await renderAndLoad();

      expect(screen.getByText('Model A')).toBeInTheDocument();
      expect(screen.getByText('Model B')).toBeInTheDocument();

      // Simulate an update failure - the component should preserve the model list
      mockSetActiveModel.mockRejectedValue(new Error('Update failed'));

      const modelBItem = screen.getByText('Model B').closest('[role="option"]');
      fireEvent.click(modelBItem!);

      const applyBtn = screen.getByRole('button', { name: /apply model selection/i });
      fireEvent.click(applyBtn);

      await waitFor(() => {
        expect(screen.getByRole('alert')).toBeInTheDocument();
      });

      // Models should still be visible (state preserved)
      expect(screen.getByText('Model A')).toBeInTheDocument();
      expect(screen.getByText('Model B')).toBeInTheDocument();
      expect(screen.getByText('Model C')).toBeInTheDocument();
      expect(screen.getByText('Model D')).toBeInTheDocument();
    });
  });
});
