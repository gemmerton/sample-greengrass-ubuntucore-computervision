# Requirements Document

## Introduction

This feature adds model selection capability to the existing React web dashboard. Operators select which AI model is active on the edge device, and the dashboard updates the `model-config` named IoT Device Shadow to trigger the ModelManagerCore on the device to switch models. The dashboard displays the current model inventory (installed models and their statuses) and the currently active model, providing feedback during the switching process.

## Glossary

- **Dashboard**: The React web application in `react-web/` that displays inference results and provides device controls.
- **Model_Selector**: The new UI component that displays available models and allows the operator to select the active model.
- **IoT_Shadow_Service**: The service layer (`iotShadowService.ts`) that communicates with the AWS IoT Data Plane to read and update device shadow state.
- **Model_Config_Shadow**: The named IoT Device Shadow (`model-config`) that stores desired and reported model state for the edge device.
- **ModelManagerCore**: The Greengrass component on the edge device that watches the shadow delta and orchestrates model installation and switching.
- **Active_Model**: The model currently serving inference requests on the edge device, identified by its model ID string in the shadow.
- **Model_Inventory**: The set of models reported as installed on the device, each with a status (`ready`, `installing`, or `failed`).
- **Operator**: A human user authenticated via Cognito who interacts with the Dashboard to manage device configuration.

## Requirements

### Requirement 1: Read Model Inventory from Shadow

**User Story:** As an Operator, I want to see which models are installed on the device and their statuses, so that I can make informed decisions about which model to activate.

#### Acceptance Criteria

1. WHEN the Operator sets a non-empty Thing Name string, THE IoT_Shadow_Service SHALL retrieve the `model-config` named shadow and extract the `reported.models` object within 10 seconds.
2. WHEN the `model-config` shadow does not exist for the specified Thing Name, THE Model_Selector SHALL display a message indicating no model configuration is available.
3. WHEN the `reported.models` field is empty or absent, THE Model_Selector SHALL display a message indicating no models are installed on the device.
4. THE IoT_Shadow_Service SHALL return each model entry with its model_id, status, model_name, version, local_path, and last_updated fields as reported in the shadow.
5. IF the IoT_Shadow_Service fails to retrieve the shadow due to a network or permissions error, THEN THE Model_Selector SHALL display an error message indicating the retrieval failure reason and allow the Operator to retry.

### Requirement 2: Display Model Inventory

**User Story:** As an Operator, I want to see a clear list of installed models with their statuses, so that I can identify which models are available for activation.

#### Acceptance Criteria

1. THE Model_Selector SHALL display each model in the Model_Inventory as a list item showing the model ID, model name, version, and current status.
2. THE Model_Selector SHALL visually distinguish models by status: `ready` models displayed as selectable, `installing` models displayed as non-selectable with a pending indicator, and `failed` models displayed as non-selectable with an unavailable indicator.
3. THE Model_Selector SHALL indicate which model is the current Active_Model with a distinct visual marker that differentiates it from non-active models in the list.
4. WHEN a model has status `failed` and a failure reason is present in the reported state, THE Model_Selector SHALL display the failure reason alongside the model entry.
5. WHEN a model has status `failed` and no failure reason is present in the reported state, THE Model_Selector SHALL display a generic indication that the model failed without a reported reason.

### Requirement 3: Display Current Active Model

**User Story:** As an Operator, I want to see which model is currently active on the device, so that I know the current inference configuration.

#### Acceptance Criteria

1. THE Model_Selector SHALL read the `reported.active_model` field from the Model_Config_Shadow and display the active model's model ID and status within the inventory list.
2. WHEN the `reported.active_model` field is absent, null, or an empty string, THE Model_Selector SHALL display a message indicating no model is currently active.
3. THE Model_Selector SHALL highlight the active model entry in the inventory list to distinguish it from other installed models.
4. IF the `reported.active_model` value references a model ID that is not present in the Model_Inventory, THEN THE Model_Selector SHALL display the active model ID with an indication that the model is not found in the inventory.

### Requirement 4: Select and Apply Active Model

**User Story:** As an Operator, I want to select a model from the inventory and set it as the active model, so that the device switches to serving inference with the selected model.

#### Acceptance Criteria

1. WHEN the Operator selects a model with status `ready` and confirms the selection, THE IoT_Shadow_Service SHALL update the Model_Config_Shadow with `desired.active_model` set to the selected model ID.
2. IF the selected model is already the Active_Model, THEN THE Model_Selector SHALL disable the apply action for that model.
3. THE Model_Selector SHALL disable selection of models that do not have status `ready`.
4. WHILE the IoT_Shadow_Service is updating the shadow, THE Model_Selector SHALL display a loading indicator and disable further selection actions until the update completes or 30 seconds elapse, whichever comes first.
5. IF the shadow update request fails, THEN THE Model_Selector SHALL display an error message with the failure reason, revert the selection to the current Active_Model, and re-enable the selection controls.
6. IF the shadow update request does not complete within 30 seconds, THEN THE Model_Selector SHALL display a timeout error message and re-enable the selection controls.

### Requirement 5: Model Switching Feedback

**User Story:** As an Operator, I want to see feedback on the model switching progress, so that I know whether the device successfully switched models.

#### Acceptance Criteria

1. WHEN the Operator applies a model selection, THE Model_Selector SHALL display a status indicating the switch is in progress and disable model selection controls until the switch completes, fails, or times out.
2. WHILE a model switch is pending, THE Model_Selector SHALL poll the Model_Config_Shadow every 5 seconds to detect when `reported.active_model` changes to the requested model ID.
3. WHEN `reported.active_model` matches the requested model ID, THE Model_Selector SHALL display a success confirmation for 5 seconds, update the displayed active model, and re-enable model selection controls.
4. WHEN the target model status changes to `failed` in the reported state during a pending switch, THE Model_Selector SHALL display an error indicating the model switch failed on the device and re-enable model selection controls.
5. IF the reported active model does not change within 90 seconds of applying the selection, THEN THE Model_Selector SHALL display a timeout warning, stop polling, and re-enable model selection controls.
6. IF a poll request to the Model_Config_Shadow fails due to a network or service error during a pending switch, THEN THE Model_Selector SHALL retry on the next poll interval and display a warning indicating connectivity issues if 3 consecutive poll attempts fail.

### Requirement 6: Authentication and Authorization

**User Story:** As an Operator, I want model selection to use the same authentication as the rest of the dashboard, so that access is secure and consistent.

#### Acceptance Criteria

1. THE IoT_Shadow_Service SHALL use the Cognito-authenticated credentials from the existing `useAuthenticatedAWS` hook when accessing the Model_Config_Shadow.
2. WHEN credentials are not available or expired, THE Model_Selector SHALL disable all controls and display a message indicating authentication is required.
3. THE IoT_Shadow_Service SHALL use the `model-config` shadow name when reading and writing model selection state, separate from the existing `inference-config` shadow used for confidence threshold.

### Requirement 7: Component Integration

**User Story:** As an Operator, I want the model selection control to appear alongside existing device controls on the dashboard, so that I have a unified interface for device management.

#### Acceptance Criteria

1. THE Dashboard SHALL render the Model_Selector component within the device controls section, in the same container as the ConfidenceThresholdControl.
2. THE Model_Selector SHALL accept a `thingName` prop that receives the same Thing Name state value provided to the ConfidenceThresholdControl.
3. IF no Thing Name is configured (empty string), THEN THE Model_Selector SHALL disable all interactive controls and display a text hint indicating that a Thing Name is required.
4. IF the Model_Selector encounters an error communicating with the device shadow, THEN THE Model_Selector SHALL display an error message indicating the failure reason and preserve any previously loaded state.
