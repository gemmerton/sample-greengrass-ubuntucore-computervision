# SMS Alert Notifications

## Goal

Extend the existing VLM alert rules to send SMS notifications when a triggered alert meets the cooldown criteria. The demo becomes tangible — edge AI detects a hazard, and a phone buzzes within seconds.

## Architecture

```
VLM Handler (device)
    │ Alert triggered + cooldown elapsed?
    ▼
MQTT: camera/alerts/sms
    │
    ▼
IoT Core Rule (SQL filter)
    │
    ▼
SNS Topic
    │
    ▼
SMS → Phone
```

**Key decision:** Cooldown is enforced on the device, not in the cloud. This eliminates Lambda and DynamoDB — the cloud path is a simple IoT Rule → SNS pipe with no state.

## How It Works

### Device Side (VLM Handler)

When `_evaluate_alerts()` returns triggered alerts:

1. Check if SMS notifications are enabled (phone number configured in shadow)
2. For each triggered alert, check if that rule's cooldown has elapsed since the last SMS for that rule
3. If cooldown has elapsed, publish a message to `camera/alerts/sms` with the alert detail
4. Record the timestamp for that rule (in-memory dict, resets on restart — acceptable for a demo)

The existing `camera/vlm` publish (which drives the React AlertBanner) is unaffected — the React app continues to receive all alerts regardless of SMS cooldown.

### Cloud Side (IoT Core Rule → SNS)

A single IoT Core Rule:

```sql
SELECT rule, detail, timestamp FROM 'camera/alerts/sms'
```

Action: Publish to an SNS topic. No filtering needed — the device already did all the filtering and cooldown enforcement.

### SNS Topic

- A standard SNS topic with SMS protocol subscription(s)
- Phone number(s) configured via the `setup_aws_resources.py` script
- Message format: short and actionable, e.g. `"ALERT: Person in trench without hard hat - Detail: Individual near excavation without PPE"`

## Configuration

### New fields in VLM config shadow (`vlm-config`)

```json
{
  "vlm_config": {
    ...existing fields...,
    "sms_enabled": true,
    "sms_phone_number": "+447700900123",
    "sms_cooldown_seconds": 300
  }
}
```

- `sms_enabled`: Master toggle. When false, no messages published to `camera/alerts/sms` regardless of alerts.
- `sms_phone_number`: E.164 format. Used by the setup script to create the SNS subscription. Stored in shadow so the React UI can display/edit it.
- `sms_cooldown_seconds`: Minimum seconds between SMS messages for the same rule. Default 300 (5 minutes). Configurable from the React UI.

### React UI additions

In the VLM config panel's "Alert Rules" section, add:
- **SMS Notifications** toggle (maps to `sms_enabled`)
- **Phone Number** input field (E.164 format, maps to `sms_phone_number`)
- **SMS Cooldown** input field in seconds (maps to `sms_cooldown_seconds`)

## MQTT Message Format (`camera/alerts/sms`)

Published by the device when a triggered alert passes cooldown:

```json
{
  "timestamp": 1717430000.123,
  "thing_name": "nuc-pro15",
  "rule": "Alert if anyone is in the trench without a hard hat",
  "triggered": true,
  "detail": "Individual observed near excavation without visible PPE",
  "risk_level": "HIGH",
  "model_id": "qwen-vl"
}
```

## AWS Resources (provisioned by setup script)

| Resource | Name/ID | Purpose |
|----------|---------|---------|
| SNS Topic | `{project_name}-sms-alerts` | Receives alert messages from IoT Rule |
| SNS Subscription | SMS to configured phone | Delivers SMS |
| IoT Core Rule | `{project_name}_sms_alert_rule` | Routes `camera/alerts/sms` → SNS |
| IAM Role | `{project_name}-iot-sns-role` | Allows IoT Core to publish to SNS |

Total: 4 resources, no Lambda, no DynamoDB.

## Cooldown Implementation (Device)

```python
# In VlmHandler.__init__
self._sms_last_sent = {}  # rule_text -> timestamp

# In the alert evaluation path
def _maybe_publish_sms_alert(self, alert, response):
    if not self.sms_enabled or not self.sms_phone_number:
        return
    rule_key = alert["rule"].lower().strip()
    now = time.time()
    last = self._sms_last_sent.get(rule_key, 0)
    if now - last < self.sms_cooldown_seconds:
        return
    self._sms_last_sent[rule_key] = now
    payload = {
        "timestamp": now,
        "thing_name": self.thing_name,
        "rule": alert["rule"],
        "triggered": True,
        "detail": alert.get("detail", ""),
        "risk_level": response.get("risk_level", "UNKNOWN"),
        "model_id": self.active_model_id,
    }
    self._publish_to_topic("camera/alerts/sms", payload)
```

The cooldown dict is in-memory. On device restart, it resets — which means one potential duplicate on restart. This is acceptable for a demo; a production system would persist to disk.

## SMS Message Content

The IoT Rule's SNS action uses a message template. SNS delivers the raw message text as the SMS body:

```
⚠️ SAFETY ALERT
${rule}
${detail}
(${timestamp})
```

Actual SMS received: `"⚠️ SAFETY ALERT\nAlert if anyone is in the trench without a hard hat\nIndividual observed near excavation without visible PPE\n(2026-06-03T14:30:00Z)"`

Character limit: SMS is 160 chars per segment. The IoT Rule should truncate `detail` to keep the message under 2 segments (320 chars) to control cost.

## Integration with setup_aws_resources.py

New method `setup_sms_alerts()` added to `AWSResourcesSetup`:
1. Create SNS topic (idempotent — `create_topic` returns existing ARN if name matches)
2. Subscribe phone number (idempotent — SNS deduplicates by endpoint)
3. Create IAM role for IoT → SNS (idempotent)
4. Create IoT Core Rule (idempotent — `create_topic_rule` or update)

New CLI args:
- `--sms-phone`: Phone number in E.164 format (e.g. `+447700900123`)
- `--sms-cooldown`: Cooldown in seconds (default 300)

Can be run standalone: `python3 scripts/setup_aws_resources.py --stage sms-alerts --sms-phone "+447700900123"`

## Cost Estimate

- SNS SMS: ~$0.04/message (UK) or ~$0.00645/message (US)
- With 5-minute cooldown and 3 alert rules: max 36 messages/hour worst case = ~$1.44/hour (UK)
- In practice during a demo: 2-5 messages total

## Testing

1. Configure an alert rule (e.g. "Alert if person visible without hard hat")
2. Set SMS cooldown to 60 seconds for testing
3. Present a scene that triggers the alert
4. Verify: SMS arrives within ~20 seconds (VLM inference + MQTT + IoT Rule + SNS)
5. Verify: No repeat SMS within cooldown window
6. Verify: React AlertBanner still fires independently (not affected by SMS cooldown)
