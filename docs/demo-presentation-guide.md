# Demo Presentation Guide

## Elevator Pitch (30 seconds)

> "This is a live edge AI system that can switch between completely different AI models — from object detection to pose estimation to vision-language models — in real time, with zero redeployment. Everything is orchestrated from the cloud using AWS IoT Greengrass, running on Intel hardware with Ubuntu Core. You change the model in the dashboard, the device adapts in seconds."

## The "So What?"

Most edge AI demos show a single model running on a device. That's table stakes.

What's hard — and what customers actually need — is **managing AI at the edge operationally**: deploying new models without truck rolls, switching workloads based on changing requirements, running fundamentally different model architectures (classical CV and large vision-language models) on the same hardware, and doing all of it securely at scale.

This demo shows that working end-to-end: a three-way partnership between **AWS** (Greengrass for orchestration, IoT Core for device management, shadows for state), **Intel** (OpenVINO for optimised inference on CPU/GPU/NPU), and **Canonical** (Ubuntu Core for immutable OS, snap packaging for model isolation). Together, they deliver a production-grade platform where edge AI is a managed service, not a bespoke deployment.

**If you're building edge AI, you don't need to solve these problems yourself. This stack exists.**

---

## Demo Flow

### The Hook (2 minutes)

Start here for every interaction. This is what grabs attention.

**1. Show live inference running**

The dashboard should already be running with a CV model active (person-detection or yolo26pose). Point the camera at yourself or the booth area.

> "This is running live on that device right there — real-time inference, no cloud round-trip. The model is running locally on Intel hardware."

**2. Switch the CV model live**

Switch from the current model to a different one (e.g. person-detection → yolo26pose) using the model selector in the dashboard.

> "Watch — I'm switching from basic person detection to a pose estimation model. The device receives the instruction via the cloud, swaps the model in OVMS, and starts serving the new model. No redeployment, no restart, no SSH."

Let them see the skeleton wireframe appear on the video feed.

**3. Reveal the architecture diagram**

Click the architecture FAB button in the bottom-right to show the system diagram.

> "Here's what's happening under the hood. The Web UI talks to AWS IoT Core via device shadows. When I change the model, the shadow's desired state updates, a delta arrives on the device, and Greengrass orchestrates the switch. That's the same mechanism you'd use to manage thousands of devices."

Close the diagram.

---

### The Full Story (5-7 minutes)

Continue here if the viewer is engaged.

**4. Show multiple CV model types**

Cycle through 2-3 CV models to demonstrate variety:
- **person-detection** → simple bounding boxes, fast (~150ms)
- **yolo26pose** → skeleton wireframes with 17 keypoints
- **faster-rcnn** → 90-class COCO detection (point at various objects)

> "These are fundamentally different model architectures — different input shapes, different output formats, different postprocessing — but the system handles all of them uniformly. The manifest describes the model, the handler adapts automatically."

**5. Switch to VLM mode**

Switch to the VLM tab and activate a vision-language model (qwen-vl or internvl2).

> "Now we go further. This isn't just classical computer vision — we can run a full vision-language model on the same device. This one actually understands the scene semantically."

Wait for a VLM result to appear in the assessment panel. Show them the JSON risk assessment.

> "It's analysing the scene for workplace safety risks, returning structured data — risk level, descriptions, categories. This is a multi-billion parameter model running locally on the edge, triggered by the CV model detecting a person."

**6. Demonstrate triggered mode**

Explain how the VLM is triggered:

> "The VLM doesn't run constantly — that would waste resources. It's triggered when the lightweight CV model detects a person. Classical CV as the tripwire, VLM as the analyst. That's the adaptive part."

**7. Add an alert rule**

In the VLM controls, add a custom alert rule (e.g. "a person not wearing a hard hat").

> "Now I'm adding a business rule. If the VLM detects this condition, it triggers an SMS alert to the site manager. No code change — just a natural language rule, evaluated by the VLM."

**8. Show the SMS alert (if possible)**

If you can trigger the alert rule, show the SMS arriving on your phone.

> "That went from camera → edge inference → IoT Core → SNS → SMS in about 15 seconds. The entire pipeline is serverless on the cloud side."

**9. Switch VLM models**

Switch between VLM models (e.g. qwen-vl → internvl2).

> "And just like the CV models, I can swap VLM models from the dashboard. internvl2 here is sideloaded from S3 — it's not even in the snap store. Greengrass pulled it down and installed it on the device automatically."

---

### Closing Points

Wrap up with the partnership and call to action:

> "Three things make this possible together:
> - **AWS Greengrass** orchestrates the entire model lifecycle from the cloud — no device access needed at scale
> - **Intel OpenVINO** gives us optimised inference across CPU, GPU, and NPU with a single model format  
> - **Ubuntu Core** gives us an immutable, secure OS with snap isolation — models can't interfere with each other or the system
>
> This is production-ready. If you're building edge AI, talk to us about how this stack can work for your use case."

---

## Tips

- **Always have inference running when people approach** — a live video feed with bounding boxes draws attention
- **Use yolo26pose as the eye-catcher** — skeleton wireframes are visually striking and immediately communicates "AI"
- **Keep the model switch moment punchy** — the 2-3 second transition where results change is the "wow" moment
- **Point at the physical device** — people need to see that this is running locally, not in a cloud demo
- **Don't deep-dive into architecture unless asked** — the diagram is there for people who want it, but lead with the live experience
- **Have the SMS alert pre-configured** — triggering it live is very impactful but only works if you can reliably trigger the rule

## Pre-Demo Checklist

- [ ] Device powered on and connected to network
- [ ] Camera positioned with clear view of booth/people
- [ ] Dashboard loaded and authenticated
- [ ] CV model running (yolo26pose recommended as default)
- [ ] VLM model ready (qwen-vl or internvl2)
- [ ] SMS alerts enabled with phone verified
- [ ] Alert rule configured (something triggerable at the booth)
- [ ] Architecture diagram tested (FAB button works)
