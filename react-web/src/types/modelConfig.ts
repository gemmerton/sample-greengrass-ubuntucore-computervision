/**
 * TypeScript types for Model Configuration Shadow
 */

export type ModelStatus = 'ready' | 'installing' | 'failed';

export interface ModelMetadata {
  model_name: string;
  version: string;
  input_shape: number[];
  local_path: string;
}

export interface ModelEntry {
  status: ModelStatus;
  model_metadata: ModelMetadata;
  failure_reason?: string;
}

export type ModelInventory = Record<string, ModelEntry>;

export interface ModelConfigShadowState {
  reported_active_model: string | null;
  reported_models: ModelInventory;
}

export type ModelSwitchState =
  | 'idle'
  | 'updating'
  | 'switching'
  | 'success'
  | 'error'
  | 'timeout';
