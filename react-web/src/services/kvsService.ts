import {
  KinesisVideoArchivedMediaClient,
  GetHLSStreamingSessionURLCommand,
  HLSPlaybackMode,
  HLSFragmentSelectorType,
  ContainerFormat,
  HLSDiscontinuityMode,
  HLSDisplayFragmentTimestamp,
} from "@aws-sdk/client-kinesis-video-archived-media";
import type { AwsCredentialIdentity } from "@aws-sdk/types";
import type { HlsSessionUrl, KvsStreamConfig } from "../types/kvs";

export async function getHlsStreamingUrl(
  config: KvsStreamConfig,
  credentials: AwsCredentialIdentity
): Promise<HlsSessionUrl> {
  const client = new KinesisVideoArchivedMediaClient({ region: config.region, credentials });
  const command = new GetHLSStreamingSessionURLCommand({
    StreamName: config.streamName,
    PlaybackMode: HLSPlaybackMode.LIVE,
    HLSFragmentSelector: {
      FragmentSelectorType: HLSFragmentSelectorType.SERVER_TIMESTAMP,
    },
    ContainerFormat: ContainerFormat.FRAGMENTED_MP4,
    DiscontinuityMode: HLSDiscontinuityMode.ALWAYS,
    DisplayFragmentTimestamp: HLSDisplayFragmentTimestamp.ALWAYS,
    Expires: 3600,
  });
  const response = await client.send(command);
  if (!response.HLSStreamingSessionURL) {
    throw new Error("No HLS URL returned from KVS");
  }
  return {
    url: response.HLSStreamingSessionURL,
    expiresAt: new Date(Date.now() + 3600 * 1000),
  };
}
