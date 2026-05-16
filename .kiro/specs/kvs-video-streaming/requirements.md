# Requirements Document

## Introduction

This feature adds AWS Kinesis Video Streams (KVS) to the existing Greengrass-based computer vision solution. The KVS Producer component runs at the edge, encoding annotated video frames (with bounding boxes and labels overlaid from inference results) into a continuous video stream and pushing it to a KVS stream in the cloud. The React dashboard embeds a KVS video player so operators can view the live annotated feed remotely. All ML inference remains on the edge device; KVS is used solely for video transport.

## Glossary

- **KVS_Producer**: The Greengrass component responsible for encoding annotated video frames and streaming them to AWS Kinesis Video Streams using the KVS Producer SDK
- **KVS_Stream**: An AWS Kinesis Video Streams resource that ingests, stores, and serves the video stream
- **Annotated_Frame**: A camera frame with inference results (bounding boxes, class labels, confidence scores) rendered onto the image pixels
- **Frame_Annotator**: The module within the KVS_Producer that draws inference results onto raw camera frames before encoding
- **Dashboard**: The React web application that displays inference results and the live video stream to authenticated operators
- **HLS_Player**: The video player component in the Dashboard that plays the KVS stream via HTTP Live Streaming (HLS)
- **Detection_Handler**: The existing Greengrass component that performs object detection inference on camera frames via OVMS gRPC
- **Camera_Handler**: The existing Greengrass component that captures images from the USB webcam
- **Edge_Device**: The Ubuntu Core device running AWS IoT Greengrass, the camera, and all inference components

## Requirements

### Requirement 1: KVS Producer Greengrass Component

**User Story:** As a system operator, I want annotated video streamed from the edge device to the cloud, so that I can monitor inference results remotely without physical access to the device.

#### Acceptance Criteria

1. THE KVS_Producer SHALL encode Annotated_Frames into an H.264 video stream and transmit the stream to the configured KVS_Stream
2. WHEN the KVS_Producer starts, IF the configured KVS_Stream does not already exist in AWS, THEN THE KVS_Producer SHALL create the KVS_Stream before beginning transmission
3. WHILE the Camera_Handler is capturing frames, THE KVS_Producer SHALL continuously produce video at the frame rate configured in the Camera_Handler capture interval
4. IF the network connection to AWS is lost, THEN THE KVS_Producer SHALL buffer frames locally for up to 120 seconds of video and resume streaming in order when connectivity is restored
5. IF the local buffer reaches its 120-second capacity while the network connection is unavailable, THEN THE KVS_Producer SHALL drop the oldest buffered frames to make room for new frames
6. THE KVS_Producer SHALL run as a Greengrass component with a recipe that declares dependencies on the Camera_Handler and Detection_Handler components
7. IF the Camera_Handler or Detection_Handler dependency is not running when the KVS_Producer starts, THEN THE KVS_Producer SHALL wait up to 30 seconds for the dependencies to become available before logging an error and retrying at 10-second intervals

### Requirement 2: Frame Annotation Pipeline

**User Story:** As a system operator, I want inference results (bounding boxes and labels) rendered directly onto the video frames, so that I can see detection results visually in the live stream without needing a separate data overlay.

#### Acceptance Criteria

1. WHEN the Detection_Handler publishes detection results on the camera/detections topic, THE Frame_Annotator SHALL draw bounding boxes on the most recent camera frame using the pixel coordinates (xmin, ymin, xmax, ymax) specified in each detection entry
2. THE Frame_Annotator SHALL render the class label and confidence score (displayed as a percentage rounded to one decimal place) as text positioned above the top-left corner of each bounding box
3. WHILE no detection results have been received since the last camera frame was captured, THE Frame_Annotator SHALL pass the raw camera frame through to the video pipeline without annotation
4. THE Frame_Annotator SHALL assign a visually distinct colour to each unique detected object class, supporting at least 10 distinct colours, and SHALL use the assigned colour consistently for both the bounding box outline and the label text of that class
5. THE Frame_Annotator SHALL complete annotation of a single frame within 50 milliseconds to avoid introducing latency into the video pipeline
6. IF a detection result arrives after the corresponding frame has already been forwarded to the video pipeline, THEN THE Frame_Annotator SHALL discard the stale detection and SHALL NOT delay frame output waiting for detection results

### Requirement 3: Edge-Only Inference Constraint

**User Story:** As a system architect, I want all ML inference to remain on the edge device, so that the solution operates with low latency and does not depend on cloud connectivity for detection results.

#### Acceptance Criteria

1. THE KVS_Producer SHALL NOT perform any ML inference operations; inference SHALL remain exclusively within the Detection_Handler and Classification_Handler components on the Edge_Device
2. THE KVS_Producer SHALL consume inference results only from the local Greengrass IPC pub/sub topics published by the Detection_Handler
3. WHILE cloud connectivity is unavailable, THE Detection_Handler SHALL continue performing inference on camera frames without interruption, maintaining the same frame processing rate as when connectivity is available
4. THE KVS_Producer SHALL NOT import or depend on any ML framework libraries (OpenVINO, TensorFlow, PyTorch, or ONNX Runtime)

### Requirement 4: KVS Stream Playback in Dashboard

**User Story:** As a system operator, I want to view the live annotated video stream in the web dashboard, so that I can monitor the edge device remotely from a browser.

#### Acceptance Criteria

1. THE Dashboard SHALL display an HLS_Player component that plays the live video from the configured KVS_Stream
2. WHEN an authenticated user navigates to the Dashboard, THE HLS_Player SHALL begin playback of the KVS_Stream within 10 seconds of page load
3. THE HLS_Player SHALL use the authenticated Cognito credentials to obtain a KVS GetHLSStreamingSessionURL for playback
4. IF the KVS_Stream is not currently receiving data, THEN THE HLS_Player SHALL display a visible status message indicating the stream is offline and stop attempting playback until the operator manually refreshes or the stream resumes
5. THE Dashboard SHALL allow the operator to view both the HLS_Player and the existing S3 image gallery simultaneously without requiring navigation between views
6. IF the GetHLSStreamingSessionURL request fails due to a network error or insufficient permissions, THEN THE HLS_Player SHALL display a status message indicating the failure reason and retry the request up to 3 times at 5-second intervals before showing a persistent error state
7. IF the Cognito credentials expire during active playback, THEN THE HLS_Player SHALL attempt to refresh the credentials and re-establish the HLS session without requiring the operator to reload the page

### Requirement 5: AWS Resource Provisioning for KVS

**User Story:** As a deployer, I want the required AWS resources (KVS stream, IAM policies) created automatically during setup, so that the streaming feature works without manual cloud configuration.

#### Acceptance Criteria

1. WHEN the setup script is executed, THE setup script SHALL create a KVS_Stream in the configured AWS region if the stream does not already exist
2. WHEN the setup script is executed, THE setup script SHALL attach an IAM policy to the Greengrass Token Exchange Role granting the KVS_Producer permissions to call kinesisvideo:PutMedia, kinesisvideo:CreateStream, kinesisvideo:DescribeStream, and kinesisvideo:GetDataEndpoint, scoped to the specific KVS_Stream resource ARN
3. WHEN the setup script is executed, THE setup script SHALL attach an IAM policy to the Cognito authenticated role granting the Dashboard permissions to call kinesisvideo:GetHLSStreamingSessionURL, kinesisvideo:GetDataEndpoint, and kinesisvideo:DescribeStream, scoped to the specific KVS_Stream resource ARN
4. WHEN the setup script is executed, THE setup script SHALL configure the KVS_Stream with a data retention period of 24 hours
5. IF the KVS_Stream already exists, THEN THE setup script SHALL skip creation and log a message confirming the existing stream will be reused
6. IF the IAM policy for the KVS_Stream is already attached to the target role, THEN THE setup script SHALL skip policy attachment and continue without error
7. IF the setup script fails to create the KVS_Stream or attach an IAM policy due to an AWS API error, THEN THE setup script SHALL log an error message indicating the failure reason and exit with a non-zero exit code

### Requirement 6: KVS Producer Configuration via Device Shadow

**User Story:** As a system operator, I want to control KVS streaming parameters (resolution, frame rate, enable/disable) remotely via the device shadow, so that I can tune the stream without redeploying the component.

#### Acceptance Criteria

1. THE KVS_Producer SHALL read its initial configuration (stream name, target frame rate, resolution, streaming enabled flag) from the kvs-config named device shadow on startup, where target frame rate is an integer between 1 and 30 fps and resolution is one of 640x480, 1280x720, or 1920x1080
2. WHEN the kvs-config shadow delta contains updated configuration values, THE KVS_Producer SHALL apply the new values within 5 seconds without restarting
3. IF the streaming enabled flag in the shadow is set to false, THEN THE KVS_Producer SHALL stop transmitting frames to the KVS_Stream and resume transmission within 5 seconds when the flag is set back to true
4. WHEN the KVS_Producer applies a configuration change or its streaming status changes, THE KVS_Producer SHALL update the kvs-config shadow reported state within 5 seconds to reflect the active stream name, frame rate, resolution, and streaming status (one of: streaming, stopped, error)
5. IF the kvs-config shadow contains an invalid configuration value (frame rate outside 1-30 fps or unrecognized resolution), THEN THE KVS_Producer SHALL reject the invalid value, retain the previous valid configuration, and report the rejection reason in the shadow reported state
6. IF the kvs-config shadow is unavailable on startup, THEN THE KVS_Producer SHALL use default configuration values (stream name from component recipe, 15 fps frame rate, 1280x720 resolution, streaming enabled) and retry reading the shadow every 30 seconds until successful

### Requirement 7: Stream Health Monitoring

**User Story:** As a system operator, I want visibility into the health of the video stream, so that I can detect and diagnose issues with the edge-to-cloud video pipeline.

#### Acceptance Criteria

1. THE KVS_Producer SHALL publish stream health metrics to the camera/kvs-status IoT Core topic every 30 seconds, including: frames sent in the preceding 30-second interval, frames dropped in the preceding 30-second interval, current bitrate in kilobits per second, and connection status (streaming, buffering, offline, error)
2. WHEN the KVS_Producer fails to transmit frames for more than 60 consecutive seconds, THE KVS_Producer SHALL publish an error status message to the camera/kvs-status topic indicating the failure reason
3. THE Dashboard SHALL display the KVS stream connection status (streaming, buffering, offline, error) alongside the HLS_Player component, updating the displayed status within 60 seconds of receiving a new status message on the camera/kvs-status topic
4. IF the KVS_Producer encounters an unrecoverable error (network unreachable for more than 300 seconds, KVS_Stream resource deleted, or authentication credentials invalid), THEN THE KVS_Producer SHALL log the error, publish a final status message to the camera/kvs-status topic, and attempt to restart the streaming pipeline with a maximum of 3 restart attempts using a 30-second delay between attempts
5. IF the KVS_Producer exhausts all 3 restart attempts without successfully resuming streaming, THEN THE KVS_Producer SHALL publish a final error status message to the camera/kvs-status topic indicating restart failure and remain in an error state until the next component deployment or manual restart
