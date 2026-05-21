/**
 * TypeScript types for Model Configuration Shadow
 */

import type { VlmConfig } from './vlm';

export type ModelStatus = 'ready' | 'installing' | 'failed';

export type ModelType = 'cv' | 'vlm';

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
  type?: ModelType;
}

export type ModelInventory = Record<string, ModelEntry>;

export interface ModelConfigShadowState {
  reported_active_model: string | null;
  reported_models: ModelInventory;
  reported_active_vlm_model: string | null;
  reported_vlm_config: VlmConfig | null;
}

export type ModelSwitchState =
  | 'idle'
  | 'updating'
  | 'switching'
  | 'success'
  | 'error'
  | 'timeout';
