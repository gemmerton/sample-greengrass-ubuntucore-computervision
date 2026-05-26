/**
 * IoT Shadow Service - Reads and updates AWS IoT Device Shadow state
 */

import { IoTDataPlaneClient, GetThingShadowCommand, UpdateThingShadowCommand } from '@aws-sdk/client-iot-data-plane';
import { ModelConfigShadowState, ModelEntry } from '../types/modelConfig';
import type { VlmConfig } from '../types/vlm';

const MODEL_CONFIG_SHADOW_NAME = 'model-config';

export interface InferenceConfig {
  confidence_threshold: number;
}

/**
 * Defensively parse a model-config shadow payload into a ModelConfigShadowState.
 * Handles malformed payloads, missing fields, and invalid values with fallback defaults.
 */
export function parseModelConfigShadow(payload: any): ModelConfigShadowState {
  const reported = payload?.state?.reported ?? {};
  const rawActiveModel = reported.active_model;
  const rawActiveVlmModel = reported.active_vlm_model;
  const rawModels = reported.models ?? {};
  const rawVlmConfig = reported.vlm_config;

  const reported_active_model =
    typeof rawActiveModel === 'string' && rawActiveModel.trim().length > 0
      ? rawActiveModel
      : null;

  const reported_active_vlm_model =
    typeof rawActiveVlmModel === 'string' && rawActiveVlmModel.trim().length > 0
      ? rawActiveVlmModel
      : null;

  // Parse each model entry defensively
  const reported_models: Record<string, ModelEntry> = {};
  for (const [modelId, entry] of Object.entries(rawModels)) {
    if (typeof entry === 'object' && entry !== null) {
      const e = entry as any;
      reported_models[modelId] = {
        status: ['ready', 'installing', 'failed'].includes(e.status)
          ? e.status
          : 'failed',
        type: e.type === 'vlm' ? 'vlm' : 'cv',
        model_metadata: {
          model_name: e.model_metadata?.model_name ?? modelId,
          version: e.model_metadata?.version ?? 'unknown',
          input_shape: Array.isArray(e.model_metadata?.input_shape)
            ? e.model_metadata.input_shape
            : [],
          local_path: e.model_metadata?.local_path ?? '',
        },
        failure_reason: e.failure_reason,
      };
    }
  }

  const reported_vlm_config: VlmConfig | null = rawVlmConfig
    ? {
        system_prompt: rawVlmConfig.system_prompt ?? '',
        user_prompt: rawVlmConfig.user_prompt ?? '',
        inference_interval: rawVlmConfig.inference_interval ?? 15,
        max_tokens: rawVlmConfig.max_tokens ?? 256,
      }
    : null;

  return { reported_active_model, reported_active_vlm_model, reported_models, reported_vlm_config };
}

export class IotShadowService {
  private getClient(credentials: any, region: string): IoTDataPlaneClient {
    return new IoTDataPlaneClient({ region, credentials });
  }

  async getConfidenceThreshold(thingName: string, credentials: any, region: string): Promise<number | null> {
    try {
      const client = this.getClient(credentials, region);
      const command = new GetThingShadowCommand({ thingName, shadowName: MODEL_CONFIG_SHADOW_NAME });
      const response = await client.send(command);
      const shadow = JSON.parse(new TextDecoder().decode(response.payload));
      return shadow?.state?.reported?.confidence_threshold ?? null;
    } catch (error: any) {
      if (error.name === 'ResourceNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async getModelConfigShadow(
    thingName: string,
    credentials: any,
    region: string
  ): Promise<ModelConfigShadowState | null> {
    try {
      const client = this.getClient(credentials, region);
      const command = new GetThingShadowCommand({
        thingName,
        shadowName: MODEL_CONFIG_SHADOW_NAME,
      });
      const response = await client.send(command);
      const shadow = JSON.parse(new TextDecoder().decode(response.payload));
      return parseModelConfigShadow(shadow);
    } catch (error: any) {
      if (error.name === 'ResourceNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async setConfidenceThreshold(thingName: string, credentials: any, region: string, threshold: number): Promise<void> {
    const client = this.getClient(credentials, region);
    const payload = JSON.stringify({
      state: { desired: { confidence_threshold: threshold } },
    });
    const command = new UpdateThingShadowCommand({
      thingName,
      shadowName: MODEL_CONFIG_SHADOW_NAME,
      payload: new TextEncoder().encode(payload),
    });
    await client.send(command);
  }

  async setActiveModel(
    thingName: string,
    credentials: any,
    region: string,
    modelId: string
  ): Promise<void> {
    try {
      const client = this.getClient(credentials, region);
      const payload = JSON.stringify({
        state: { desired: { active_model: modelId } },
      });
      const command = new UpdateThingShadowCommand({
        thingName,
        shadowName: MODEL_CONFIG_SHADOW_NAME,
        payload: new TextEncoder().encode(payload),
      });
      await client.send(command);
    } catch (error: any) {
      throw new Error(
        `Failed to set active model '${modelId}' for thing '${thingName}': ${error.message ?? error}`
      );
    }
  }

  async setActiveVlmModel(
    thingName: string,
    credentials: any,
    region: string,
    modelId: string
  ): Promise<void> {
    const client = this.getClient(credentials, region);
    const payload = JSON.stringify({
      state: { desired: { active_vlm_model: modelId } },
    });
    const command = new UpdateThingShadowCommand({
      thingName,
      shadowName: MODEL_CONFIG_SHADOW_NAME,
      payload: new TextEncoder().encode(payload),
    });
    await client.send(command);
  }

  async getVlmConfig(
    thingName: string,
    credentials: any,
    region: string
  ): Promise<VlmConfig | null> {
    const state = await this.getModelConfigShadow(thingName, credentials, region);
    return state?.reported_vlm_config ?? null;
  }

  async setVlmConfig(
    thingName: string,
    credentials: any,
    region: string,
    config: VlmConfig
  ): Promise<void> {
    const client = this.getClient(credentials, region);
    const payload = JSON.stringify({
      state: { desired: { vlm_config: config } },
    });
    const command = new UpdateThingShadowCommand({
      thingName,
      shadowName: MODEL_CONFIG_SHADOW_NAME,
      payload: new TextEncoder().encode(payload),
    });
    await client.send(command);
  }

  async getInferenceInterval(thingName: string, credentials: any, region: string): Promise<number | null> {
    try {
      const client = this.getClient(credentials, region);
      const command = new GetThingShadowCommand({ thingName, shadowName: MODEL_CONFIG_SHADOW_NAME });
      const response = await client.send(command);
      const shadow = JSON.parse(new TextDecoder().decode(response.payload));
      return shadow?.state?.reported?.inference_interval ?? shadow?.state?.desired?.inference_interval ?? null;
    } catch (error: any) {
      if (error.name === 'ResourceNotFoundException') {
        return null;
      }
      throw error;
    }
  }

  async setInferenceInterval(thingName: string, credentials: any, region: string, interval: number): Promise<void> {
    const client = this.getClient(credentials, region);
    const payload = JSON.stringify({
      state: { desired: { inference_interval: interval } },
    });
    const command = new UpdateThingShadowCommand({
      thingName,
      shadowName: MODEL_CONFIG_SHADOW_NAME,
      payload: new TextEncoder().encode(payload),
    });
    await client.send(command);
  }
}

export const iotShadowService = new IotShadowService();
