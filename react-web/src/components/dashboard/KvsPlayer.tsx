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

export const KvsPlayer: React.FC<KvsPlayerProps> = ({
  streamName, region, credentials, streamStatus,
}) => {
  const videoRef = useRef<HTMLVideoElement>(null);
  const hlsRef = useRef<Hls | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStream = useCallback(async () => {
    if (!streamName) return;
    setLoading(true);
    setError(null);
    let lastError: Error | null = null;

    for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
      try {
        const { url } = await getHlsStreamingUrl(
          { streamName, region }, credentials);
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
          if (data.fatal) { setError("Playback error"); }
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

  useEffect(() => {
    if (!streamName) { setLoading(false); return; }
    loadStream();
    return () => { hlsRef.current?.destroy(); };
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
