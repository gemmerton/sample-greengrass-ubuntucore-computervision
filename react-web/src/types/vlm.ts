export type RiskLevel = 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
export type RiskCategory = 'machinery' | 'ppe' | 'ergonomic' | 'environmental' | 'other';

export interface Risk {
  description: string;
  severity: RiskLevel;
  category: RiskCategory | string;
}

export interface VlmAlert {
  rule: string;
  triggered: boolean;
  detail: string;
}

export interface VlmResponse {
  risk_level: RiskLevel;
  summary: string;
  risks: Risk[];
  alerts?: VlmAlert[];
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
  mode: 'continuous' | 'triggered';
  trigger_classes: string[];
  trigger_cooldown: number;
  alert_rules: string[];
  sms_enabled: boolean;
  sms_cooldown_seconds: number;
}

export interface VlmQuery {
  query_id: string;
  question: string;
  timestamp: number;
}

export interface VlmQueryResponse {
  query_id: string;
  question: string;
  answer: string;
  timestamp: number;
  inference_time_ms: number;
}
