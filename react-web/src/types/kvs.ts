export interface KvsStreamConfig {
  streamName: string;
  region: string;
}

export interface HlsSessionUrl {
  url: string;
  expiresAt: Date;
}

export type StreamStatus = "streaming" | "buffering" | "offline" | "error";

export interface KvsHealthMessage {
  timestamp: string;
  frames_sent: number;
  frames_dropped: number;
  bitrate_kbps: number;
  connection_status: StreamStatus;
  error_reason: string | null;
}
