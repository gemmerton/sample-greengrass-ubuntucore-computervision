import {
  KinesisVideoClient,
  GetDataEndpointCommand,
} from "@aws-sdk/client-kinesis-video";
import {
  KinesisVideoArchivedMediaClient,
  GetHLSStreamingSessionURLCommand,
  HLSPlaybackMode,
  HLSFragmentSelectorType,
  ContainerFormat,
  HLSDiscontinuityMode,
  HLSDisplayFragmentTimestamp,
} from "@aws-sdk/client-kinesis-video-archived-media";
import type { AwsCredentialIdentity, Provider } from "@aws-sdk/types";
import type { HlsSessionUrl, KvsStreamConfig } from "../types/kvs";

export type CredentialsInput = AwsCredentialIdentity | Provider<AwsCredentialIdentity>;

export async function getHlsStreamingUrl(
  config: KvsStreamConfig,
  credentials: CredentialsInput
): Promise<HlsSessionUrl> {
  // Resolve credentials fresh each call to avoid using stale temporary creds.
  const resolved = typeof credentials === "function" ? await credentials() : credentials;

  // KVS requires a two-step URL resolution: first obtain the stream-specific
  // data endpoint, then call GetHLSStreamingSessionURL against that endpoint.
  // Using the main regional endpoint for GetHLSStreamingSessionURL returns 400.
  const kvsClient = new KinesisVideoClient({ region: config.region, credentials: resolved });
  const endpointResponse = await kvsClient.send(
    new GetDataEndpointCommand({
      StreamName: config.streamName,
      APIName: "GET_HLS_STREAMING_SESSION_URL",
    })
  );
  const dataEndpoint = endpointResponse.DataEndpoint;
  if (!dataEndpoint) {
    throw new Error("No data endpoint returned from KVS GetDataEndpoint");
  }

  const client = new KinesisVideoArchivedMediaClient({
    region: config.region,
    credentials: resolved,
    endpoint: dataEndpoint,
  });
  const command = new GetHLSStreamingSessionURLCommand({
    StreamName: config.streamName,
    PlaybackMode: HLSPlaybackMode.LIVE,
    HLSFragmentSelector: {
      FragmentSelectorType: HLSFragmentSelectorType.PRODUCER_TIMESTAMP,
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
