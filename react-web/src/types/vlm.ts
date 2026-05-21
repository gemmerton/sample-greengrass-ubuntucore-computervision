export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
export type RiskCategory = 'machinery' | 'ppe' | 'ergonomic' | 'environmental' | 'other';

export interface Risk {
  description: string;
  severity: RiskLevel;
  category: RiskCategory | string;
}

export interface VlmResponse {
  risk_level: RiskLevel;
  summary: string;
  risks: Risk[];
}

export interface VlmResult {
  timestamp: number;
  model_id: string;
  model_name: string;
  inference_time_ms: number;
  prompt: {
    system: string;
    user: string;
  };
  response: VlmResponse | null;
  raw_output: string;
}

export interface VlmConfig {
  system_prompt: string;
  user_prompt: string;
  inference_interval: number;
  max_tokens: number;
}
