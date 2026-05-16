# Implementation Plan: Dashboard Model Selection

## Overview

This plan implements the Model Selector component for the React dashboard, enabling operators to view the model inventory on an edge device and switch the active inference model via the `model-config` IoT Device Shadow. The implementation extends the existing `iotShadowService`, creates a new `ModelSelector` component, and integrates it into the Dashboard layout.

## Tasks

- [x] 1. Create TypeScript types for model config
  - [x] 1.1 Create model config type definitions
    - Create `react-web/src/types/modelConfig.ts`
    - Define `ModelStatus` type: `'ready' | 'installing' | 'failed'`
    - Define `ModelMetadata` interface: `model_name`, `version`, `input_shape`, `local_path`
    - Define `ModelEntry` interface: `status`, `model_metadata`, optional `failure_reason`
    - Define `ModelInventory` type: `Record<string, ModelEntry>`
    - Define `ModelConfigShadowState` interface: `reported_active_model`, `reported_models`
    - Define `ModelSwitchState` type: `'idle' | 'updating' | 'switching' | 'success' | 'error' | 'timeout'`
    - _Requirements: 1.4, 2.1_

- [x] 2. Extend iotShadowService with model-config shadow methods
  - [x] 2.1 Add `getModelConfigShadow` method
    - Modify `react-web/src/services/iotShadowService.ts`
    - Add `MODEL_CONFIG_SHADOW_NAME = 'model-config'` constant
    - Implement `getModelConfigShadow(thingName, credentials, region)` that calls `GetThingShadowCommand` with shadow name `model-config`
    - Parse the response payload using defensive parsing: normalize `active_model` (treat null/undefined/empty as null), parse each model entry with fallback defaults for missing fields
    - Return `ModelConfigShadowState | null` (null when shadow does not exist / `ResourceNotFoundException`)
    - _Requirements: 1.1, 1.2, 1.4, 6.1, 6.3_

  - [x] 2.2 Add `setActiveModel` method
    - Implement `setActiveModel(thingName, credentials, region, modelId)` that calls `UpdateThingShadowCommand`
    - Construct payload: `{ state: { desired: { active_model: modelId } } }`
    - Throw on failure with descriptive error message
    - _Requirements: 4.1, 6.1, 6.3_

  - [x] 2.3 Add `parseModelConfigShadow` helper function
    - Implement the defensive parsing function from the design document
    - Handle malformed payloads: missing `state.reported`, missing `models`, invalid status values, missing metadata fields
    - Apply fallback defaults: `model_name` defaults to model ID, `version` defaults to `'unknown'`, `input_shape` defaults to empty array, `local_path` defaults to empty string
    - _Requirements: 1.4, 1.5_

- [x] 3. Create ModelSelector component
  - [x] 3.1 Create component skeleton with state management
    - Create `react-web/src/components/controls/ModelSelector.tsx`
    - Accept `ModelSelectorProps`: `thingName: string`, optional `className`
    - Implement internal state: `models`, `activeModelId`, `selectedModelId`, `switchState`, `errorMessage`, `pollFailCount`
    - Use `useAuthenticatedAWS` hook for credentials
    - On mount (when `thingName` is non-empty and credentials available): call `getModelConfigShadow` and populate state
    - When `thingName` is empty: display hint message, disable all controls
    - When credentials unavailable: display authentication required message, disable controls
    - _Requirements: 6.1, 6.2, 7.2, 7.3_

  - [x] 3.2 Implement model inventory display
    - Render each model as a list item showing: model ID, model name, version, status badge
    - Style `ready` models as selectable (clickable), `installing` models with a pending spinner, `failed` models as greyed out / unavailable
    - Highlight the active model with a distinct visual marker (e.g., "Active" badge or border)
    - Display failure reason for `failed` models (or generic "Failed" if no reason provided)
    - Handle case where `reported.active_model` references a model not in inventory: show model ID with "not found" indicator
    - Handle empty models map: display "No models installed on device" message
    - Handle null shadow response: display "No model configuration available" message
    - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4_

  - [x] 3.3 Implement model selection and apply action
    - On click of a `ready` model: set `selectedModelId` to that model's ID
    - Disable selection of non-`ready` models (no click handler)
    - Render "Apply" button enabled only when `selectedModelId` differs from `activeModelId` and `switchState` is `idle`
    - On "Apply" click: transition to `updating` state, call `setActiveModel`, handle success/failure/timeout
    - On success: transition to `switching` state, begin polling
    - On failure: transition to `error` state, display error message, revert `selectedModelId` to `activeModelId`, re-enable controls
    - On 30s timeout: transition to `error` state with timeout message, re-enable controls
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6_

  - [x] 3.4 Implement polling and switching feedback
    - In `switching` state: poll `getModelConfigShadow` every 5 seconds
    - On each poll: check if `reported.active_model` matches the target model ID
    - If match: transition to `success` state, update `activeModelId`, show success for 5 seconds, then transition to `idle`
    - If target model status becomes `failed`: transition to `error` state with device failure message
    - If 90 seconds elapsed: transition to `timeout` state, stop polling
    - Track consecutive poll failures: if 3 in a row, display connectivity warning (continue polling)
    - Clean up polling interval on unmount or state transition out of `switching`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x] 3.5 Implement error display and retry
    - Display error messages for: load failure (with retry button), update failure, update timeout, switch failure, switch timeout
    - On load failure retry: re-call `getModelConfigShadow`, preserve previously loaded state if retry also fails
    - Display connectivity warning inline (not blocking) during poll failures
    - _Requirements: 1.5, 4.5, 4.6, 5.4, 5.5, 5.6, 7.4_

- [x] 4. Create ModelSelector styles
  - [x] 4.1 Create component CSS
    - Create `react-web/src/components/controls/ModelSelector.css`
    - Style model list items with status-based visual treatment
    - Style active model highlight (distinct from selected)
    - Style selected model indicator (before apply)
    - Style status badges: ready (green), installing (amber/spinner), failed (red)
    - Style disabled state for non-ready models
    - Style loading/switching overlay
    - Style error and success messages
    - Match existing dashboard design language (reference `ConfidenceThresholdControl` styles)
    - _Requirements: 2.2, 2.3_

- [x] 5. Integrate ModelSelector into Dashboard
  - [x] 5.1 Add ModelSelector to Dashboard component
    - Modify `react-web/src/components/dashboard/Dashboard.tsx`
    - Import `ModelSelector` component
    - Render `<ModelSelector thingName={thingName} />` in the configuration controls section alongside `ConfidenceThresholdControl`
    - _Requirements: 7.1, 7.2_

- [x] 6. Write unit tests
  - [x] 6.1 Test iotShadowService model-config methods
    - Test `getModelConfigShadow` returns parsed state for valid shadow
    - Test `getModelConfigShadow` returns null for `ResourceNotFoundException`
    - Test `getModelConfigShadow` throws on network/permission errors
    - Test `parseModelConfigShadow` handles missing fields with defaults
    - Test `parseModelConfigShadow` normalizes empty/null active_model to null
    - Test `setActiveModel` constructs correct payload structure
    - Test `setActiveModel` throws on API failure
    - _Requirements: 1.1, 1.2, 1.4, 1.5, 4.1_

  - [x] 6.2 Test ModelSelector component rendering
    - Test renders "Thing Name required" hint when thingName is empty
    - Test renders "authentication required" when credentials are null
    - Test renders "no model configuration" when shadow returns null
    - Test renders "no models installed" when models map is empty
    - Test renders all models with correct ID, name, version, status
    - Test active model has distinct visual marker
    - Test active model not in inventory shows "not found" indicator
    - Test failed model displays failure reason
    - Test failed model without reason shows generic message
    - _Requirements: 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.2, 3.3, 3.4, 7.3_

  - [x] 6.3 Test ModelSelector interaction and state machine
    - Test selecting a ready model updates selectedModelId
    - Test non-ready models are not selectable
    - Test Apply button disabled when selected equals active
    - Test Apply button disabled during updating/switching states
    - Test loading indicator shown during shadow update
    - Test error message and revert on update failure
    - Test timeout error after 30s on update
    - Test success confirmation shown for 5s after switch completes
    - Test switch failure detected when target model status becomes failed
    - Test switch timeout after 90s of polling
    - Test connectivity warning after 3 consecutive poll failures
    - Test previously loaded state preserved on refresh error
    - _Requirements: 4.2, 4.3, 4.4, 4.5, 4.6, 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 7.4_

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["2.1", "2.2", "2.3"] },
    { "id": 2, "tasks": ["3.1", "4.1"] },
    { "id": 3, "tasks": ["3.2", "3.3"] },
    { "id": 4, "tasks": ["3.4", "3.5"] },
    { "id": 5, "tasks": ["5.1"] },
    { "id": 6, "tasks": ["6.1", "6.2", "6.3"] }
  ]
}
```

## Notes

- Total: 15 sub-tasks across 6 task groups
- The implementation follows the established pattern from `ConfidenceThresholdControl` for consistency
- All shadow operations use the `model-config` shadow name, separate from `inference-config`
- Polling is implemented with `setInterval` + cleanup in `useEffect` return
- The 30s update timeout uses `AbortController` or a racing Promise
- The 90s switch timeout uses a timestamp comparison on each poll
- CSS follows the existing dashboard design language
- No property-based tests in this task list (can be added as a follow-up)
