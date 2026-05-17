# System Architecture

End-to-end integration between Ubuntu Core snaps, AWS Greengrass components, AWS cloud services, and the React dashboard.

```mermaid
flowchart TD
    CAM["📷 USB Camera\n/dev/video0"]

    subgraph DEVICE["Edge Device — Ubuntu Core"]

        subgraph GG["aws-iot-greengrass snap"]
            CHC["CameraHandlerCore\nfallback snapshot capture\n(when KvsProducer not running)"]
            KVS_P["KvsProducer\nv4l2src → tee → annotate → H.264\nsnapshots every 10 s"]
            DH["DetectionHandler\nobject detection gRPC client"]
            CLH["ClassificationHandler\nimage classification gRPC client"]
            MMC["ModelManagerCore\nmodel lifecycle · snap or S3 install\nwrites OVMS config to content mount"]
        end

        subgraph OVMS_S["ovms-engine snap"]
            OVMS["OpenVINO Model Server\ngRPC :9000"]
        end

        subgraph KGS["kvs-gstreamer snap"]
            GSTLIBS["GStreamer runtime\n+ libgstkvssink.so\n(content interface slot)"]
        end

    end

    subgraph AWS["☁ AWS Cloud"]
        IOT["IoT Core\nMQTT broker + WebSocket"]
        SHADOW["Device Shadow Service\n■ kvs-config\n■ model-config"]
        KVS_SVC["Kinesis Video Streams"]
        S3_SVC["S3\nmodel artifacts"]
        COGNITO["Cognito\nuser pools + identity"]
    end

    subgraph UI["💻 React Dashboard"]
        AUTH_UI["Login"]
        PLAYER["KVS Live Player\nHLS via hls.js"]
        FEED_UI["Inference Feed"]
        MGMT_UI["Model Manager\n+ KVS settings"]
    end

    %% ── Camera to edge ──────────────────────────────────────────
    CAM -->|"v4l2src (GStreamer)"| KVS_P
    CAM -->|"OpenCV"| CHC

    %% ── Local IPC PubSub: camera/images ─────────────────────────
    CHC -..->|"camera/images  IPC PubSub\n(active only without KvsProducer)"| DH
    CHC -..->|"camera/images  IPC PubSub\n(active only without KvsProducer)"| CLH
    KVS_P -->|"camera/images snapshots\nIPC PubSub"| DH
    KVS_P -->|"camera/images snapshots\nIPC PubSub"| CLH

    %% ── Inference ───────────────────────────────────────────────
    DH -->|"gRPC inference"| OVMS
    CLH -->|"gRPC inference"| OVMS

    %% ── Snap content interfaces ─────────────────────────────────
    GSTLIBS -.->|"content interface\nGStreamer libs + kvssink"| KVS_P
    MMC -->|"content interface\nmodel config JSON + model files"| OVMS_S

    %% ── Edge → IoT Core (MQTT publish) ─────────────────────────
    DH -->|"camera/detections"| IOT
    CLH -->|"camera/classifications"| IOT
    KVS_P -->|"camera/kvs-status  health metrics"| IOT
    MMC -->|"model-config  reported state"| IOT
    KVS_P -->|"kvs-config  reported state"| IOT

    %% ── IoT Core → Edge (MQTT subscribe) ────────────────────────
    IOT -->|"camera/detections\n→ annotation overlay"| KVS_P
    IOT -->|"kvs-config delta\n→ reconfigure pipeline"| KVS_P
    IOT -->|"model-config delta\n→ install / remove models"| MMC

    %% ── Shadow sync ─────────────────────────────────────────────
    IOT <-->|"shadow sync\n(local ShadowManager)"| SHADOW

    %% ── Edge → AWS services ─────────────────────────────────────
    KVS_P -->|"PutMedia  H.264 stream"| KVS_SVC
    MMC -->|"GetObject  model download"| S3_SVC

    %% ── React Dashboard ─────────────────────────────────────────
    AUTH_UI -->|"authenticate"| COGNITO
    COGNITO -->|"temporary AWS credentials"| PLAYER
    COGNITO -->|"temporary AWS credentials"| FEED_UI
    COGNITO -->|"temporary AWS credentials"| MGMT_UI
    PLAYER -->|"GetDataEndpoint\nGetHLSStreamingSessionURL"| KVS_SVC
    FEED_UI <-->|"MQTT over WebSocket\ncamera/detections\ncamera/classifications\ncamera/kvs-status"| IOT
    MGMT_UI -->|"update desired state\n(kvs-config · model-config)"| SHADOW
```

---

## Key Message Topics

| Topic | Direction | Publisher | Subscriber(s) |
|-------|-----------|-----------|----------------|
| `camera/images` | IPC PubSub (local) | CameraHandlerCore *or* KvsProducer | DetectionHandler, ClassificationHandler |
| `camera/detections` | MQTT (IoT Core) | DetectionHandler | KvsProducer, React Dashboard |
| `camera/classifications` | MQTT (IoT Core) | ClassificationHandler | React Dashboard |
| `camera/kvs-status` | MQTT (IoT Core) | KvsProducer | React Dashboard |
| `$aws/.../kvs-config/update/delta` | MQTT (IoT Core shadow) | Device Shadow Service | KvsProducer |
| `$aws/.../model-config/update/delta` | MQTT (IoT Core shadow) | Device Shadow Service | ModelManagerCore |

## Snap Boundaries & Interfaces

| Interface | Provider snap | Consumer | What crosses |
|-----------|--------------|----------|--------------|
| `gstreamer-kvs` content slot | kvs-gstreamer | KvsProducer (aws-iot-greengrass) | GStreamer runtime libs + `libgstkvssink.so` |
| `inference-config` content slot | ovms-engine | ModelManagerCore (aws-iot-greengrass) | OVMS `models_config.json` write path |
| `inference-models` content slot | ovms-engine | ModelManagerCore (aws-iot-greengrass) | Model files directory write path |
| `camera` plug | aws-iot-greengrass | — | Access to `/dev/video*` |
