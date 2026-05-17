import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import React from "react";

// Mock hls.js
vi.mock("hls.js", () => ({
  default: class MockHls {
    static isSupported() { return true; }
    loadSource = vi.fn();
    attachMedia = vi.fn();
    on = vi.fn();
    destroy = vi.fn();
    static Events = { MANIFEST_PARSED: "hlsManifestParsed", ERROR: "hlsError" };
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
});
