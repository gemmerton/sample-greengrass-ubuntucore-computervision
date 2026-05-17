import React, { useEffect, useRef, useState, useCallback } from "react";
import Hls from "hls.js";
import type { AwsCredentialIdentity } from "@aws-sdk/types";
import type { StreamStatus } from "../../types/kvs";
import { getHlsStreamingUrl } from "../../services/kvsService";
import "./KvsPlayer.css";

interface KvsPlayerProps {
  streamName: string;
  region: string;
  credentials: AwsCredentialIdentity;
  streamStatus?: StreamStatus;
}

const MAX_RETRIES = 3;
const RETRY_INTERVAL_MS = import.meta.env.VITEST ? 0 : 5000;
// Proactively refresh HLS session URL this many ms before it expires (5 min)
const URL_REFRESH_BEFORE_EXPIRY_MS = 5 * 60 * 1000;

export const KvsPlayer: React.FC<KvsPlayerProps> = ({
  streamName, region, credentials, streamStatus,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Stable ref so the HLS error callback can call the latest loadStream closure
  const loadStreamRef = useRef<(() => Promise<void>) | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStream = useCallback(async () => {
    if (refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
    if (!streamName) return;
    setLoading(true);
    setError(null);
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        const { url, expiresAt } = await getHlsStreamingUrl(
          { streamName, region }, credentials);
        const msUntilRefresh = expiresAt.getTime() - Date.now() - URL_REFRESH_BEFORE_EXPIRY_MS;
        if (msUntilRefresh > 0) {
          refreshTimerRef.current = setTimeout(
            () => loadStreamRef.current?.(), msUntilRefresh);
        }
        if (hlsRef.current) { hlsRef.current.destroy(); }
        const hls = new Hls();
        hlsRef.current = hls;
        hls.loadSource(url);
        if (videoRef.current) { hls.attachMedia(videoRef.current); }
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          videoRef.current?.play().catch(() => {});
          setLoading(false);
        });
        hls.on(Hls.Events.ERROR, (_: unknown, data: { fatal: boolean }) => {
          if (data.fatal) { loadStreamRef.current?.(); }
        });
        return;
      } catch (e) {
        lastError = e as Error;
        if (attempt < MAX_RETRIES - 1) {
          await new Promise(r => setTimeout(r, RETRY_INTERVAL_MS));
        }
      }
    }
    setError(lastError?.message ?? "Failed to load stream");
    setLoading(false);
  }, [streamName, region, credentials]);

  // Keep loadStreamRef pointing at the latest loadStream closure so callbacks
  // fired by hls.js or the refresh timer always call the current version.
  useEffect(() => {
    loadStreamRef.current = loadStream;
  }, [loadStream]);

  useEffect(() => {
    if (!streamName) { setLoading(false); return; }
    loadStream();
    return () => {
      hlsRef.current?.destroy();
      if (refreshTimerRef.current) { clearTimeout(refreshTimerRef.current); }
    };
  }, [loadStream, streamName]);

  if (!streamName) {
    return (
      <div className="kvs-player-container">
        <div className="kvs-player-overlay status-offline">Stream Offline</div>
        <video data-testid="kvs-video" />
      </div>
    );
  }

  return (
    <div className="kvs-player-container">
      <video ref={videoRef} data-testid="kvs-video" muted playsInline />
      {loading && <div className="kvs-player-overlay">Loading...</div>}
      {error && <div className="kvs-player-overlay status-error">Error: {error}</div>}
      {streamStatus && (
        <div className={`kvs-player-overlay status-${streamStatus}`}>
          {streamStatus}
        </div>
      )}
    </div>
  );
};
