export interface BoundingBox {
  xmin: number;
  ymin: number;
  xmax: number;
  ymax: number;
}

export interface Detection {
  label: string;
  score: number;
  box: BoundingBox;
}

export interface Classification {
  label: string;
  confidence: number;
  class_index: number;
}

export interface DetectionResults {
  detections: Detection[];
  count: number;
}

export interface ClassificationResults {
  classifications: Classification[];
}

export interface InferenceResult {
  timestamp: number;
  model_id: string;
  model_name: string;
  result_type: 'detection' | 'classification';
  results: DetectionResults | ClassificationResults;
  inference_time_ms: number;
  frame_width?: number;
  frame_height?: number;
  confidence_threshold?: number;
}
