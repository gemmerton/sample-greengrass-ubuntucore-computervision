import React, { useState, useEffect, useRef } from 'react';
import type { InferenceResult } from '../../types/inference';
import './EdgeLatencyIndicator.css';

interface EdgeLatencyIndicatorProps {
  latestResult: InferenceResult | null;
  videoElement: HTMLVideoElement | null;
}

function formatTime(epoch: number): string {
  const date = new Date(epoch * 1000);
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

export const EdgeLatencyIndicator: React.FC<EdgeLatencyIndicatorProps> = ({
  latestResult,
  videoElement,
}) => {
  const [videoDelaySec, setVideoDelaySec] = useState<number | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!videoElement) return;

    const updateDelay = () => {
      if (!videoElement.buffered.length || videoElement.paused) return;
      const bufferedEnd = videoElement.buffered.end(videoElement.buffered.length - 1);
      const delay = bufferedEnd - videoElement.currentTime;
      const totalEstimatedDelay = delay + 3;
      setVideoDelaySec(Math.round(totalEstimatedDelay));
    };

    intervalRef.current = setInterval(updateDelay, 1000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [videoElement]);

  if (!latestResult) return null;

  const edgeTime = latestResult.timestamp;
  const videoTime = videoDelaySec !== null ? edgeTime - videoDelaySec : null;

  return (
    <div className="edge-latency">
      <div className="edge-latency__row">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>
        </svg>
        <span className="edge-latency__label">Edge detected</span>
        <span className="edge-latency__time">{formatTime(edgeTime)}</span>
      </div>
      {videoTime !== null && (
        <div className="edge-latency__row">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="2" y="7" width="20" height="15" rx="2" ry="2"/><polyline points="17 2 12 7 7 2"/>
          </svg>
          <span className="edge-latency__label">Video showing</span>
          <span className="edge-latency__time">{formatTime(videoTime)}</span>
        </div>
      )}
      {videoDelaySec !== null && videoDelaySec > 0 && (
        <div className="edge-latency__advantage">
          Edge inference {videoDelaySec}s ahead of video
        </div>
      )}
    </div>
  );
};
