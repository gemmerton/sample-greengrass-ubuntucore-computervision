# Unified Inference Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace static Detection/Classification handlers with a single shadow-reactive InferenceHandler, and add bounding box overlay + results panel to the React dashboard.

**Architecture:** A unified InferenceHandler Greengrass component captures frames via OpenCV at a configurable interval, reads model metadata from the local `model-config` shadow, calls OVMS gRPC, and publishes results to `camera/inference`. The React dashboard subscribes via IoT Core MQTT and renders bounding boxes on a canvas overlay atop the KVS video player, plus a structured results panel.

**Tech Stack:** Python 3 (OpenCV, ovmsclient, awsiotsdk), React 19 + TypeScript + Vite, aws-iot-device-sdk-v2, hls.js

---

## File Structure

### Greengrass Component (new)

| File | Responsibility |
|------|---------------|
| `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py` | Main handler: frame capture, OVMS inference, result publishing |
| `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/requirements.txt` | Python dependencies |
| `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/get-pip.py` | pip bootstrap (copy from existing) |
| `greengrass-components/recipes/com.example.InferenceHandler-1.0.0.yaml` | Component recipe with shadow/MQTT permissions |

### React Dashboard (new/modify)

| File | Responsibility |
|------|---------------|
| `react-web/src/components/dashboard/InferenceOverlay.tsx` | Canvas overlay drawing bounding boxes/labels on video |
| `react-web/src/components/dashboard/InferencePanel.tsx` | Structured results panel (detections table / classifications list) |
| `react-web/src/components/dashboard/Dashboard.tsx` | MODIFY: integrate overlay and panel |
| `react-web/src/types/inference.ts` | TypeScript types for inference results |
| `react-web/src/hooks/useInferenceResults.ts` | Hook to parse MQTT messages into typed inference results |

---

## Task 1: Create InferenceHandler recipe

**Files:**
- Create: `greengrass-components/recipes/com.example.InferenceHandler-1.0.0.yaml`

- [ ] **Step 1: Write the recipe file**

```yaml
---
RecipeFormatVersion: '2020-01-25'
ComponentName: com.example.InferenceHandler
ComponentVersion: '1.0.0'
ComponentDescription: 'Unified inference handler - captures frames, runs OVMS inference, publishes results via MQTT'
ComponentPublisher: AWS
ComponentDependencies:
  aws.greengrass.ShadowManager:
    VersionRequirement: '^2.0.0'
  aws.greengrass.TokenExchangeService:
    VersionRequirement: '^2.0.0'
ComponentConfiguration:
  DefaultConfiguration:
    CameraDevice: "/dev/video1"
    OvmsGrpcUrl: "localhost:9000"
    InferenceInterval: "1.0"
    ConfidenceThreshold: "0.5"
    PubTopic: "camera/inference"
    accessControl:
      aws.greengrass.ShadowManager:
        com.example.InferenceHandler:shadow:1:
          policyDescription: 'Read model-config shadow for active model metadata'
          operations:
            - 'aws.greengrass#GetThingShadow'
          resources:
            - '$aws/things/*/shadow/name/model-config'
      aws.greengrass.ipc.mqttproxy:
        com.example.InferenceHandler:mqttproxy:1:
          policyDescription: 'Publish inference results to IoT Core'
          operations:
            - 'aws.greengrass#PublishToIoTCore'
          resources:
            - 'camera/inference'
        com.example.InferenceHandler:mqttproxy:2:
          policyDescription: 'Subscribe to model-config shadow delta for live config changes'
          operations:
            - 'aws.greengrass#SubscribeToIoTCore'
          resources:
            - '$aws/things/*/shadow/name/model-config/update/delta'
Manifests:
- Platform:
    os: all
    runtime: '*'
  Lifecycle:
    Install:
      Script: |
        /bin/bash -c 'set -e && \
        python3 -m venv --without-pip venv/ && \
        source venv/bin/activate && \
        python3 {artifacts:path}/get-pip.py && \
        python3 -m pip install -r {artifacts:path}/requirements.txt && \
        deactivate'
    Run:
      Script: |
        /bin/bash -c 'set -e && \
        source venv/bin/activate && \
        export AWS_IOT_THING_NAME="{iot:thingName}" && \
        export CAMERA_DEVICE="{configuration:/CameraDevice}" && \
        export OVMS_GRPC_URL="{configuration:/OvmsGrpcUrl}" && \
        export INFERENCE_INTERVAL="{configuration:/InferenceInterval}" && \
        export CONFIDENCE_THRESHOLD="{configuration:/ConfidenceThreshold}" && \
        export PUB_TOPIC="{configuration:/PubTopic}" && \
        python3 {artifacts:path}/inference_handler.py'
  Artifacts:
    - Uri: inference_handler.py
      Unarchive: NONE
    - Uri: get-pip.py
      Unarchive: NONE
    - Uri: requirements.txt
      Unarchive: NONE
```

- [ ] **Step 2: Create requirements.txt**

Create `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/requirements.txt`:

```
awsiotsdk==1.21.0
ovmsclient
numpy
opencv-python-headless
```

- [ ] **Step 3: Copy get-pip.py from existing component**

```bash
cp greengrass-components/artifacts/com.example.ModelManagerCore/1.0.0/get-pip.py \
   greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/get-pip.py
```

- [ ] **Step 4: Commit**

```bash
git add greengrass-components/recipes/com.example.InferenceHandler-1.0.0.yaml \
        greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/requirements.txt \
        greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/get-pip.py
git commit -m "feat(InferenceHandler): add recipe and dependencies"
```

---

## Task 2: Implement InferenceHandler - core loop

**Files:**
- Create: `greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py`

- [ ] **Step 1: Write the inference handler**

```python
"""InferenceHandler - Unified shadow-reactive inference for edge computer vision.

Captures frames from the camera at a configurable interval, reads active model
metadata from the model-config local shadow, calls OVMS gRPC for inference,
and publishes results to camera/inference via IoT Core MQTT.
"""

import os
import sys
import time
import json
import logging
import traceback

import cv2
import numpy as np
from ovmsclient import make_grpc_client
import awsiot.greengrasscoreipc.clientv2 as clientv2

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

SHADOW_NAME = "model-config"


class InferenceHandler:

    def __init__(self):
        self.thing_name = os.environ.get("AWS_IOT_THING_NAME", "")
        self.camera_device = os.environ.get("CAMERA_DEVICE", "/dev/video1")
        self.ovms_url = os.environ.get("OVMS_GRPC_URL", "localhost:9000")
        self.inference_interval = float(os.environ.get("INFERENCE_INTERVAL", "1.0"))
        self.confidence_threshold = float(os.environ.get("CONFIDENCE_THRESHOLD", "0.5"))
        self.pub_topic = os.environ.get("PUB_TOPIC", "camera/inference")

        self.ipc_client = clientv2.GreengrassCoreIPCClientV2()
        self.model_metadata = None
        self.active_model_id = None
        self.cap = None

        logger.info(
            "InferenceHandler initialized: thing=%s camera=%s ovms=%s interval=%ss",
            self.thing_name, self.camera_device, self.ovms_url, self.inference_interval,
        )

    def run(self):
        self._subscribe_to_shadow_delta()
        self._load_active_model()

        while True:
            if self.model_metadata is None:
                logger.info("No active model, waiting...")
                time.sleep(5)
                self._load_active_model()
                continue

            try:
                self._capture_and_infer()
            except Exception as e:
                logger.error("Inference cycle failed: %s", e)
                traceback.print_exc()

            time.sleep(self.inference_interval)

    def _subscribe_to_shadow_delta(self):
        if not self.thing_name:
            return
        delta_topic = f"$aws/things/{self.thing_name}/shadow/name/{SHADOW_NAME}/update/delta"
        self.ipc_client.subscribe_to_iot_core(
            topic_name=delta_topic,
            qos="1",
            on_stream_event=self._on_shadow_delta,
            on_stream_error=lambda e: logger.error("Delta stream error: %s", e),
            on_stream_closed=lambda: logger.warning("Delta stream closed"),
        )
        logger.info("Subscribed to shadow delta: %s", delta_topic)

    def _on_shadow_delta(self, event):
        try:
            payload = json.loads(event.message.payload)
            state = payload.get("state", {})
            if "active_model" in state:
                new_model = state["active_model"]
                logger.info("Shadow delta: active_model changed to '%s'", new_model)
                self._load_active_model()
            if "confidence_threshold" in state:
                self.confidence_threshold = float(state["confidence_threshold"])
                logger.info("Confidence threshold updated to %s", self.confidence_threshold)
            if "inference_interval" in state:
                self.inference_interval = float(state["inference_interval"])
                logger.info("Inference interval updated to %ss", self.inference_interval)
        except Exception as e:
            logger.error("Failed to handle shadow delta: %s", e)

    def _load_active_model(self):
        if not self.thing_name:
            return
        try:
            response = self.ipc_client.get_thing_shadow(
                thing_name=self.thing_name, shadow_name=SHADOW_NAME
            )
            shadow = json.loads(response.payload)
            reported = shadow.get("state", {}).get("reported", {})
            desired = shadow.get("state", {}).get("desired", {})

            target_model_id = desired.get("active_model")

            models = reported.get("models", {})
            if not models:
                self.model_metadata = None
                self.active_model_id = None
                return

            if target_model_id and target_model_id in models:
                entry = models[target_model_id]
            else:
                target_model_id = next(
                    (mid for mid, m in models.items() if m.get("status") == "ready"),
                    None,
                )
                if not target_model_id:
                    self.model_metadata = None
                    self.active_model_id = None
                    return
                entry = models[target_model_id]

            if entry.get("status") != "ready":
                logger.info("Model '%s' not ready (status=%s)", target_model_id, entry.get("status"))
                self.model_metadata = None
                self.active_model_id = None
                return

            metadata = entry.get("model_metadata", {})
            if self.active_model_id != target_model_id:
                logger.info("Active model changed: %s -> %s", self.active_model_id, target_model_id)
                self.active_model_id = target_model_id
                self.model_metadata = metadata
                logger.info("Model metadata: %s", json.dumps(metadata, indent=2))
        except Exception as e:
            logger.error("Failed to load active model from shadow: %s", e)

    def _capture_and_infer(self):
        if self.cap is None or not self.cap.isOpened():
            self.cap = cv2.VideoCapture(self.camera_device)
            if not self.cap.isOpened():
                logger.error("Cannot open camera: %s", self.camera_device)
                return

        ret, frame = self.cap.read()
        if not ret:
            logger.warning("Failed to capture frame")
            self.cap.release()
            self.cap = None
            return

        frame_height, frame_width = frame.shape[:2]

        model_name = self.model_metadata.get("model_name", "")
        input_name = self.model_metadata.get("input_name", "data")
        input_shape = self.model_metadata.get("input_shape", [1, 3, 224, 224])
        output_names = self.model_metadata.get("output_names", [])

        preprocessed = self._preprocess(frame, input_shape)

        start_time = time.time()
        try:
            client = make_grpc_client(self.ovms_url)
            result = client.predict({input_name: preprocessed}, model_name)
        except Exception as e:
            logger.error("OVMS predict failed: %s", e)
            return
        inference_time_ms = round((time.time() - start_time) * 1000, 1)

        result_payload = self._postprocess(
            result, output_names, frame_width, frame_height, inference_time_ms
        )
        if result_payload:
            self._publish(result_payload)

    def _preprocess(self, frame, input_shape):
        if len(input_shape) == 4:
            _, c_or_h, h_or_w, w_or_c = input_shape
            if c_or_h <= 4:
                # NCHW format
                target_h, target_w = h_or_w, w_or_c
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                transposed = np.transpose(rgb, (2, 0, 1))
                return np.expand_dims(transposed, axis=0).astype(np.float32)
            else:
                # NHWC format
                target_h, target_w = c_or_h, h_or_w
                resized = cv2.resize(frame, (target_w, target_h))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                return np.expand_dims(rgb, axis=0).astype(np.float32)
        resized = cv2.resize(frame, (224, 224))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        return np.expand_dims(np.transpose(rgb, (2, 0, 1)), axis=0).astype(np.float32)

    def _postprocess(self, result, output_names, frame_width, frame_height, inference_time_ms):
        if "detection_out" in output_names or self._is_detection_output(result):
            return self._postprocess_detection(result, frame_width, frame_height, inference_time_ms)
        else:
            return self._postprocess_classification(result, inference_time_ms)

    def _is_detection_output(self, result):
        for key, val in result.items():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[2] > 1 and val.shape[3] == 7:
                return True
        return False

    def _postprocess_detection(self, result, frame_width, frame_height, inference_time_ms):
        output = None
        for key, val in result.items():
            if hasattr(val, 'shape') and len(val.shape) == 4 and val.shape[3] == 7:
                output = val
                break
        if output is None:
            for key, val in result.items():
                output = val
                break
        if output is None:
            return None

        detections = []
        output = np.squeeze(output)
        for det in output:
            if len(det) < 7:
                continue
            confidence = float(det[2])
            if confidence < self.confidence_threshold:
                continue
            label_id = int(det[1])
            xmin = float(np.clip(det[3], 0, 1))
            ymin = float(np.clip(det[4], 0, 1))
            xmax = float(np.clip(det[5], 0, 1))
            ymax = float(np.clip(det[6], 0, 1))
            detections.append({
                "label": f"class_{label_id}",
                "score": round(confidence, 4),
                "box": {
                    "xmin": round(xmin, 4),
                    "ymin": round(ymin, 4),
                    "xmax": round(xmax, 4),
                    "ymax": round(ymax, 4),
                },
            })

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "detection",
            "results": {"detections": detections, "count": len(detections)},
            "inference_time_ms": inference_time_ms,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "confidence_threshold": self.confidence_threshold,
        }

    def _postprocess_classification(self, result, inference_time_ms):
        output = None
        for key, val in result.items():
            output = val
            break
        if output is None:
            return None

        probs = np.squeeze(output)
        top_k = 5
        top_indices = np.argsort(probs)[::-1][:top_k]
        classifications = []
        for idx in top_indices:
            conf = float(probs[idx])
            if conf < self.confidence_threshold:
                continue
            classifications.append({
                "label": f"class_{idx}",
                "confidence": round(conf, 4),
                "class_index": int(idx),
            })

        return {
            "timestamp": time.time(),
            "model_id": self.active_model_id,
            "model_name": self.model_metadata.get("model_name", ""),
            "result_type": "classification",
            "results": {"classifications": classifications},
            "inference_time_ms": inference_time_ms,
            "confidence_threshold": self.confidence_threshold,
        }

    def _publish(self, payload):
        try:
            encoded = json.dumps(payload).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=self.pub_topic,
                qos="1",
                payload=encoded,
            )
            logger.debug("Published to %s: %s detections/classifications",
                         self.pub_topic, payload.get("results", {}).get("count", "?"))
        except Exception as e:
            logger.error("Failed to publish inference results: %s", e)


if __name__ == "__main__":
    handler = InferenceHandler()
    handler.run()
```

- [ ] **Step 2: Commit**

```bash
git add greengrass-components/artifacts/com.example.InferenceHandler/1.0.0/inference_handler.py
git commit -m "feat(InferenceHandler): implement unified inference handler"
```

---

## Task 3: Create React inference types and hook

**Files:**
- Create: `react-web/src/types/inference.ts`
- Create: `react-web/src/hooks/useInferenceResults.ts`

- [ ] **Step 1: Create inference types**

Create `react-web/src/types/inference.ts`:

```typescript
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
```

- [ ] **Step 2: Create useInferenceResults hook**

Create `react-web/src/hooks/useInferenceResults.ts`:

```typescript
import { useState, useEffect, useCallback } from 'react';
import { useMqtt } from '../contexts/MqttContext';
import type { InferenceResult } from '../types/inference';

const INFERENCE_TOPIC = 'camera/inference';
const MAX_HISTORY = 20;

export function useInferenceResults() {
  const { state } = useMqtt();
  const [latestResult, setLatestResult] = useState<InferenceResult | null>(null);
  const [history, setHistory] = useState<InferenceResult[]>([]);

  useEffect(() => {
    if (!state.lastMessage) return;
    if (state.lastMessage.topic !== INFERENCE_TOPIC) return;

    try {
      const parsed: InferenceResult = JSON.parse(state.lastMessage.payload);
      if (parsed.result_type && parsed.results) {
        setLatestResult(parsed);
        setHistory((prev) => [parsed, ...prev].slice(0, MAX_HISTORY));
      }
    } catch {
      // Not a valid inference message
    }
  }, [state.lastMessage]);

  const clearHistory = useCallback(() => {
    setHistory([]);
    setLatestResult(null);
  }, []);

  return { latestResult, history, clearHistory };
}
```

- [ ] **Step 3: Commit**

```bash
git add react-web/src/types/inference.ts react-web/src/hooks/useInferenceResults.ts
git commit -m "feat(react): add inference result types and hook"
```

---

## Task 4: Create InferenceOverlay component

**Files:**
- Create: `react-web/src/components/dashboard/InferenceOverlay.tsx`

- [ ] **Step 1: Write the overlay component**

```typescript
import React, { useRef, useEffect } from 'react';
import type { InferenceResult, Detection } from '../../types/inference';

interface InferenceOverlayProps {
  result: InferenceResult | null;
  videoElement: HTMLVideoElement | null;
}

const BOX_COLOR = '#00ff88';
const TEXT_COLOR = '#ffffff';
const TEXT_BG = 'rgba(0, 0, 0, 0.7)';
const FONT = '14px monospace';

export const InferenceOverlay: React.FC<InferenceOverlayProps> = ({
  result,
  videoElement,
}) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !videoElement) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const rect = videoElement.getBoundingClientRect();
    canvas.width = rect.width;
    canvas.height = rect.height;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!result) return;

    if (result.result_type === 'detection') {
      const detections = (result.results as { detections: Detection[] }).detections;
      drawDetections(ctx, detections, canvas.width, canvas.height);
    } else if (result.result_type === 'classification') {
      const classifications = (result.results as { classifications: { label: string; confidence: number }[] }).classifications;
      if (classifications.length > 0) {
        drawClassificationBadge(ctx, classifications[0], canvas.width);
      }
    }
  }, [result, videoElement]);

  useEffect(() => {
    if (!videoElement) return;
    const observer = new ResizeObserver(() => {
      const canvas = canvasRef.current;
      if (canvas) {
        const rect = videoElement.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;
      }
    });
    observer.observe(videoElement);
    return () => observer.disconnect();
  }, [videoElement]);

  return (
    <canvas
      ref={canvasRef}
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
      }}
    />
  );
};

function drawDetections(
  ctx: CanvasRenderingContext2D,
  detections: Detection[],
  canvasWidth: number,
  canvasHeight: number
) {
  for (const det of detections) {
    const x = det.box.xmin * canvasWidth;
    const y = det.box.ymin * canvasHeight;
    const w = (det.box.xmax - det.box.xmin) * canvasWidth;
    const h = (det.box.ymax - det.box.ymin) * canvasHeight;

    ctx.strokeStyle = BOX_COLOR;
    ctx.lineWidth = 2;
    ctx.strokeRect(x, y, w, h);

    const label = `${det.label} ${(det.score * 100).toFixed(0)}%`;
    ctx.font = FONT;
    const textWidth = ctx.measureText(label).width;

    ctx.fillStyle = TEXT_BG;
    ctx.fillRect(x, y - 20, textWidth + 8, 20);

    ctx.fillStyle = TEXT_COLOR;
    ctx.fillText(label, x + 4, y - 5);
  }
}

function drawClassificationBadge(
  ctx: CanvasRenderingContext2D,
  top: { label: string; confidence: number },
  canvasWidth: number
) {
  const label = `${top.label} ${(top.confidence * 100).toFixed(1)}%`;
  ctx.font = '16px monospace';
  const textWidth = ctx.measureText(label).width;

  const padding = 10;
  const x = canvasWidth - textWidth - padding * 2 - 10;
  const y = 10;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
  ctx.beginPath();
  ctx.roundRect(x, y, textWidth + padding * 2, 32, 6);
  ctx.fill();

  ctx.fillStyle = '#00ff88';
  ctx.fillText(label, x + padding, y + 22);
}
```

- [ ] **Step 2: Commit**

```bash
git add react-web/src/components/dashboard/InferenceOverlay.tsx
git commit -m "feat(react): add InferenceOverlay canvas component"
```

---

## Task 5: Create InferencePanel component

**Files:**
- Create: `react-web/src/components/dashboard/InferencePanel.tsx`

- [ ] **Step 1: Write the panel component**

```typescript
import React from 'react';
import type { InferenceResult, Detection, Classification } from '../../types/inference';

interface InferencePanelProps {
  latestResult: InferenceResult | null;
  history: InferenceResult[];
  className?: string;
}

export const InferencePanel: React.FC<InferencePanelProps> = ({
  latestResult,
  history,
  className = '',
}) => {
  if (!latestResult) {
    return (
      <div className={`inference-panel ${className}`}>
        <div className="inference-panel__empty">
          Waiting for inference results...
        </div>
      </div>
    );
  }

  return (
    <div className={`inference-panel ${className}`}>
      <div className="inference-panel__header">
        <span className="inference-panel__model">{latestResult.model_name}</span>
        <span className="inference-panel__timing">{latestResult.inference_time_ms}ms</span>
        <span className="inference-panel__type">{latestResult.result_type}</span>
      </div>

      <div className="inference-panel__results">
        {latestResult.result_type === 'detection' ? (
          <DetectionTable
            detections={(latestResult.results as { detections: Detection[] }).detections}
          />
        ) : (
          <ClassificationList
            classifications={(latestResult.results as { classifications: Classification[] }).classifications}
          />
        )}
      </div>

      <div className="inference-panel__history">
        <span className="inference-panel__history-label">
          History ({history.length})
        </span>
        <div className="inference-panel__history-list">
          {history.slice(0, 10).map((r, i) => (
            <div key={i} className="inference-panel__history-item">
              <span>{new Date(r.timestamp * 1000).toLocaleTimeString()}</span>
              <span>{r.result_type === 'detection'
                ? `${(r.results as { count: number }).count} detections`
                : `${(r.results as { classifications: Classification[] }).classifications.length} classes`
              }</span>
              <span>{r.inference_time_ms}ms</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

const DetectionTable: React.FC<{ detections: Detection[] }> = ({ detections }) => {
  if (detections.length === 0) {
    return <div className="inference-panel__no-results">No detections</div>;
  }
  return (
    <table className="inference-panel__table">
      <thead>
        <tr><th>Label</th><th>Score</th><th>Position</th></tr>
      </thead>
      <tbody>
        {detections.map((d, i) => (
          <tr key={i}>
            <td>{d.label}</td>
            <td>{(d.score * 100).toFixed(1)}%</td>
            <td className="inference-panel__coords">
              ({d.box.xmin.toFixed(2)}, {d.box.ymin.toFixed(2)}) -
              ({d.box.xmax.toFixed(2)}, {d.box.ymax.toFixed(2)})
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

const ClassificationList: React.FC<{ classifications: Classification[] }> = ({ classifications }) => {
  if (classifications.length === 0) {
    return <div className="inference-panel__no-results">No classifications</div>;
  }
  return (
    <div className="inference-panel__class-list">
      {classifications.map((c, i) => (
        <div key={i} className="inference-panel__class-item">
          <span className="inference-panel__class-label">{c.label}</span>
          <div className="inference-panel__class-bar">
            <div
              className="inference-panel__class-bar-fill"
              style={{ width: `${c.confidence * 100}%` }}
            />
          </div>
          <span className="inference-panel__class-score">
            {(c.confidence * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
};
```

- [ ] **Step 2: Commit**

```bash
git add react-web/src/components/dashboard/InferencePanel.tsx
git commit -m "feat(react): add InferencePanel results display component"
```

---

## Task 6: Integrate overlay and panel into Dashboard

**Files:**
- Modify: `react-web/src/components/dashboard/Dashboard.tsx`
- Modify: `react-web/src/components/dashboard/KvsPlayer.tsx`

- [ ] **Step 1: Update KvsPlayer to expose video ref**

Modify `KvsPlayer.tsx` to accept an `onVideoReady` callback that passes the video element reference to the parent:

Add to the `KvsPlayerProps` interface:
```typescript
onVideoReady?: (videoEl: HTMLVideoElement) => void;
```

In the `loadStream` callback, after the video starts playing, call the callback:
```typescript
hls.on(Hls.Events.MANIFEST_PARSED, () => {
  videoRef.current?.play().catch(() => {});
  setLoading(false);
  setPlaying(true);
  if (videoRef.current && onVideoReady) {
    onVideoReady(videoRef.current);
  }
});
```

- [ ] **Step 2: Update Dashboard to integrate inference components**

In `Dashboard.tsx`, add imports and state:

```typescript
import { InferenceOverlay } from './InferenceOverlay';
import { InferencePanel } from './InferencePanel';
import { useInferenceResults } from '../../hooks/useInferenceResults';
```

Inside `DashboardContent`, add:
```typescript
const { latestResult, history } = useInferenceResults();
const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
```

Wrap the KvsPlayer in a positioned container and add the overlay:
```typescript
<article className="dashboard__card dashboard__card--video" style={{ position: 'relative' }}>
  <KvsPlayer
    streamName={import.meta.env.VITE_KVS_STREAM_NAME ?? ''}
    region={region ?? config.aws.region}
    credentials={credentials}
    onVideoReady={setVideoElement}
  />
  <InferenceOverlay result={latestResult} videoElement={videoElement} />
</article>
```

Add the InferencePanel beside or below the video card:
```typescript
<article className="dashboard__card dashboard__card--inference">
  <InferencePanel latestResult={latestResult} history={history} />
</article>
```

- [ ] **Step 3: Ensure MQTT subscribes to inference topic**

The dashboard should auto-subscribe to `camera/inference` when connected. In the Dashboard's MQTT connection logic, either:
- Set the default topic to `camera/inference` in the MqttTopicInput, OR
- Add a second subscription alongside the user-configured topic

The simplest approach: change the `defaultTopic` prop on `MqttProvider` to `camera/inference`:
```typescript
<MqttProvider autoConnect={false} defaultTopic="camera/inference">
```

- [ ] **Step 4: Commit**

```bash
git add react-web/src/components/dashboard/Dashboard.tsx \
        react-web/src/components/dashboard/KvsPlayer.tsx
git commit -m "feat(react): integrate inference overlay and panel into dashboard"
```

---

## Task 7: Add CSS for InferencePanel

**Files:**
- Modify: whichever CSS/SCSS file the dashboard uses (check `react-web/src/` for `.css` or `.scss` files)

- [ ] **Step 1: Add InferencePanel styles**

```css
.inference-panel {
  padding: 1rem;
  font-family: monospace;
  font-size: 0.85rem;
  overflow-y: auto;
  max-height: 400px;
}

.inference-panel__header {
  display: flex;
  gap: 1rem;
  align-items: center;
  margin-bottom: 0.75rem;
  padding-bottom: 0.5rem;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}

.inference-panel__model {
  font-weight: bold;
  color: #00ff88;
}

.inference-panel__timing {
  color: #aaa;
}

.inference-panel__type {
  padding: 2px 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.1);
  text-transform: uppercase;
  font-size: 0.7rem;
}

.inference-panel__empty {
  color: #888;
  text-align: center;
  padding: 2rem;
}

.inference-panel__no-results {
  color: #666;
  padding: 0.5rem 0;
}

.inference-panel__table {
  width: 100%;
  border-collapse: collapse;
}

.inference-panel__table th,
.inference-panel__table td {
  text-align: left;
  padding: 4px 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.inference-panel__table th {
  color: #888;
  font-weight: normal;
}

.inference-panel__coords {
  font-size: 0.75rem;
  color: #888;
}

.inference-panel__class-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.inference-panel__class-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.inference-panel__class-label {
  min-width: 80px;
}

.inference-panel__class-bar {
  flex: 1;
  height: 6px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 3px;
  overflow: hidden;
}

.inference-panel__class-bar-fill {
  height: 100%;
  background: #00ff88;
  border-radius: 3px;
}

.inference-panel__class-score {
  min-width: 50px;
  text-align: right;
  color: #aaa;
}

.inference-panel__history {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
}

.inference-panel__history-label {
  color: #888;
  font-size: 0.75rem;
  text-transform: uppercase;
}

.inference-panel__history-list {
  margin-top: 0.5rem;
}

.inference-panel__history-item {
  display: flex;
  justify-content: space-between;
  padding: 2px 0;
  color: #666;
  font-size: 0.75rem;
}
```

- [ ] **Step 2: Commit**

```bash
git add react-web/src/...  # the CSS file
git commit -m "style(react): add InferencePanel and overlay styles"
```

---

## Task 8: Remove old handlers from deployment, deploy InferenceHandler

**Files:**
- Modify: `deploy_greengrass_components.py` (if needed to exclude old handlers)

- [ ] **Step 1: Deploy updated components**

Run the deployment script (which picks up all recipes in the `recipes/` directory). Since we're keeping the old recipe files for now (in case of rollback), exclude them from deployment by moving to an archived folder:

```bash
mv greengrass-components/recipes/com.example.DetectionHandler-1.0.0.yaml \
   greengrass-components/archived/recipes/
mv greengrass-components/recipes/com.example.ClassificationHandler-1.0.0.yaml \
   greengrass-components/archived/recipes/
```

- [ ] **Step 2: Deploy to device**

```bash
AWS_PROFILE="gemmerto+ubuntu-Admin" .venv/bin/python3 deploy_greengrass_components.py \
  --stage full --thing-name ucore-kvs-3 --s3-bucket gg-ge-test --region eu-west-1
```

- [ ] **Step 3: Verify InferenceHandler starts and publishes**

```bash
ssh <device> 'sudo tail -20 /var/snap/aws-iot-greengrass/common/greengrass/v2/logs/com.example.InferenceHandler.log'
```

Expected: logs showing frame capture and inference results being published.

- [ ] **Step 4: Commit archive move**

```bash
git add greengrass-components/recipes/ greengrass-components/archived/recipes/
git commit -m "refactor: archive old Detection/Classification handlers, deploy InferenceHandler"
```

---

## Task 9: Test end-to-end on device

- [ ] **Step 1: Ensure model is active**

Push desired state to shadow if not already set:
```bash
aws iot-data update-thing-shadow --thing-name ucore-kvs-3 --shadow-name model-config \
  --region eu-west-1 --profile "gemmerto+ubuntu-Admin" \
  --cli-binary-format raw-in-base64-out \
  --payload '{"state":{"desired":{"models":{"faster-rcnn":{"source":"snap"}},"active_model":"faster-rcnn"}}}'
```

- [ ] **Step 2: Verify MQTT messages arriving**

Subscribe to the topic from the CLI:
```bash
aws iot-data subscribe --topic camera/inference --region eu-west-1 --profile "gemmerto+ubuntu-Admin"
```

Or check via the AWS IoT Core MQTT test client in the console.

- [ ] **Step 3: Start React dev server and verify overlay**

```bash
cd react-web && npm run dev
```

Open browser, connect MQTT to `camera/inference`, verify:
- Bounding boxes appear over the video
- InferencePanel shows structured results
- Model name and inference time display correctly

- [ ] **Step 4: Test model switch**

Use the ModelSelector in the dashboard to switch to `efficientnet`. Verify:
- InferenceHandler picks up the new model within 15 seconds
- Results change from `detection` type to `classification` type
- Overlay switches from bounding boxes to classification badge
