import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, act } from "@testing-library/react";
import React from "react";

// Track the most recently created Hls instance so tests can inspect registered callbacks.
let lastHlsInstance: any = null;

// Mock hls.js
vi.mock("hls.js", () => ({
  default: class MockHls {
    static isSupported() { return true; }
    static Events = { MANIFEST_PARSED: "hlsManifestParsed", ERROR: "hlsError" };
    loadSource = vi.fn();
    attachMedia = vi.fn();
    on = vi.fn();
    destroy = vi.fn();
    constructor() { lastHlsInstance = this; }
  },
}));

// Mock kvsService
vi.mock("../../../services/kvsService", () => ({
  getHlsStreamingUrl: vi.fn(),
}));

import { getHlsStreamingUrl } from "../../../services/kvsService";
import { KvsPlayer } from "../KvsPlayer";

const mockCredentials = {
  accessKeyId: "AKIA",
  secretAccessKey: "secret",
  sessionToken: "token",
};

describe("KvsPlayer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    lastHlsInstance = null;
  });

  it("renders a video element", () => {
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt: new Date(Date.now() + 3600000),
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByTestId("kvs-video")).toBeInTheDocument();
  });

  it("shows loading state while fetching URL", () => {
    vi.mocked(getHlsStreamingUrl).mockReturnValue(new Promise(() => {}));
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
  });

  it("retries GetHLSStreamingSessionURL 3 times on failure", async () => {
    vi.mocked(getHlsStreamingUrl).mockRejectedValue(new Error("network error"));
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    await waitFor(() =>
      expect(screen.getByText(/error/i)).toBeInTheDocument(),
      { timeout: 4000 }
    );
    expect(getHlsStreamingUrl).toHaveBeenCalledTimes(3);
  });

  it("shows offline status when stream name is empty", () => {
    render(
      <KvsPlayer streamName="" region="us-east-1"
                 credentials={mockCredentials} />
    );
    expect(screen.getByText(/stream offline/i)).toBeInTheDocument();
  });

  it("displays stream status from health message prop", () => {
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt: new Date(Date.now() + 3600000),
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials}
                 streamStatus="buffering" />
    );
    expect(screen.getByText(/buffering/i)).toBeInTheDocument();
  });

  it("fetches a new URL when a fatal HLS error occurs", async () => {
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt: new Date(Date.now() + 3600000),
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );

    await waitFor(() => expect(getHlsStreamingUrl).toHaveBeenCalledTimes(1));

    // Trigger fatal HLS error via the registered callback
    const errorHandler = lastHlsInstance?.on.mock.calls.find(
      (c: any) => c[0] === "hlsError"
    )?.[1];
    await act(async () => { errorHandler?.(null, { fatal: true }); });

    await waitFor(() => expect(getHlsStreamingUrl).toHaveBeenCalledTimes(2));
  });

  it("schedules a proactive URL refresh before the session expires", async () => {
    const setTimeoutSpy = vi.spyOn(global, "setTimeout");
    const expiresAt = new Date(Date.now() + 60 * 60 * 1000); // 1 hour
    vi.mocked(getHlsStreamingUrl).mockResolvedValue({
      url: "https://example.com/stream.m3u8",
      expiresAt,
    });
    render(
      <KvsPlayer streamName="test-stream" region="us-east-1"
                 credentials={mockCredentials} />
    );
    await waitFor(() => expect(getHlsStreamingUrl).toHaveBeenCalledTimes(1));

    // A setTimeout call with a delay of ~55 minutes (5 min before 60 min expiry)
    const refreshCall = setTimeoutSpy.mock.calls.find(
      (c) => typeof c[1] === "number" && (c[1] as number) > 50 * 60 * 1000
    );
    expect(refreshCall).toBeTruthy();
    setTimeoutSpy.mockRestore();
  });
});
