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
