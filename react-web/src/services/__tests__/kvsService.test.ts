import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock both KVS SDK packages before importing the service
const mockGetDataEndpoint = vi.fn();
const mockGetHLSStreamingSessionURL = vi.fn();

vi.mock("@aws-sdk/client-kinesis-video", () => ({
  KinesisVideoClient: vi.fn(() => ({ send: mockGetDataEndpoint })),
  GetDataEndpointCommand: vi.fn((input) => input),
}));

vi.mock("@aws-sdk/client-kinesis-video-archived-media", () => ({
  KinesisVideoArchivedMediaClient: vi.fn(() => ({ send: mockGetHLSStreamingSessionURL })),
  GetHLSStreamingSessionURLCommand: vi.fn((input) => input),
  HLSPlaybackMode: { LIVE: "LIVE" },
  HLSFragmentSelectorType: { SERVER_TIMESTAMP: "SERVER_TIMESTAMP" },
  ContainerFormat: { FRAGMENTED_MP4: "FRAGMENTED_MP4" },
  HLSDiscontinuityMode: { ALWAYS: "ALWAYS" },
  HLSDisplayFragmentTimestamp: { ALWAYS: "ALWAYS" },
}));

import { getHlsStreamingUrl } from "../kvsService";
import { KinesisVideoArchivedMediaClient } from "@aws-sdk/client-kinesis-video-archived-media";

const config = { streamName: "test-stream", region: "us-east-1" };
const credentials = { accessKeyId: "A", secretAccessKey: "S", sessionToken: "T" };
const DATA_ENDPOINT = "https://b-12345678.kinesisvideo.us-east-1.amazonaws.com";

describe("getHlsStreamingUrl", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGetDataEndpoint.mockResolvedValue({ DataEndpoint: DATA_ENDPOINT });
    mockGetHLSStreamingSessionURL.mockResolvedValue({
      HLSStreamingSessionURL: "https://example.com/stream.m3u8",
    });
  });

  it("calls GetDataEndpoint before GetHLSStreamingSessionURL", async () => {
    await getHlsStreamingUrl(config, credentials);
    expect(mockGetDataEndpoint).toHaveBeenCalledTimes(1);
    expect(mockGetHLSStreamingSessionURL).toHaveBeenCalledTimes(1);
    // GetDataEndpoint must be called first
    expect(mockGetDataEndpoint.mock.invocationCallOrder[0])
      .toBeLessThan(mockGetHLSStreamingSessionURL.mock.invocationCallOrder[0]);
  });

  it("passes the data endpoint URL to KinesisVideoArchivedMediaClient", async () => {
    await getHlsStreamingUrl(config, credentials);
    expect(KinesisVideoArchivedMediaClient).toHaveBeenCalledWith(
      expect.objectContaining({ endpoint: DATA_ENDPOINT })
    );
  });

  it("returns HLS URL and expiry from the response", async () => {
    const result = await getHlsStreamingUrl(config, credentials);
    expect(result.url).toBe("https://example.com/stream.m3u8");
    expect(result.expiresAt.getTime()).toBeGreaterThan(Date.now());
  });

  it("throws when GetDataEndpoint returns no endpoint", async () => {
    mockGetDataEndpoint.mockResolvedValue({ DataEndpoint: undefined });
    await expect(getHlsStreamingUrl(config, credentials)).rejects.toThrow(
      "No data endpoint"
    );
  });

  it("throws when GetHLSStreamingSessionURL returns no URL", async () => {
    mockGetHLSStreamingSessionURL.mockResolvedValue({ HLSStreamingSessionURL: undefined });
    await expect(getHlsStreamingUrl(config, credentials)).rejects.toThrow(
      "No HLS URL"
    );
  });
});
