# SMS Alert Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend VLM alert rules to send SMS notifications via IoT Core Rule → SNS, with device-side cooldown to prevent duplicate messages.

**Architecture:** The VLM handler on the device publishes to a dedicated `camera/alerts/sms` MQTT topic when an alert triggers and cooldown has elapsed. An IoT Core Rule forwards those messages to an SNS topic with an SMS subscription. AWS infrastructure is provisioned via `setup_aws_resources.py --stage sms-alerts`. The React UI gets toggle + cooldown controls in the Alert Rules section.

**Tech Stack:** Python/boto3 (setup script, device handler), AWS IoT Core Rules, AWS SNS, React/TypeScript (UI controls)

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py` | SMS cooldown logic + publish to `camera/alerts/sms` |
| Modify | `react-web/src/types/vlm.ts` | Add `sms_enabled` and `sms_cooldown_seconds` to VlmConfig |
| Modify | `react-web/src/components/controls/VlmPromptEditor.tsx` | Add SMS toggle + cooldown UI in Alert Rules section |
| Modify | `react-web/src/components/controls/VlmPromptEditor.css` | Styles for SMS toggle |
| Modify | `scripts/setup_aws_resources.py` | Add `setup_sms_alerts()` method and `--stage sms-alerts` CLI |

---

## Task 1: Add SMS fields to VlmConfig type

**Files:**
- Modify: `react-web/src/types/vlm.ts`

- [ ] **Step 1: Add sms_enabled and sms_cooldown_seconds to VlmConfig interface**

In `react-web/src/types/vlm.ts`, add two fields to the `VlmConfig` interface after `alert_rules`:

```typescript
export interface VlmConfig {
  system_prompt: string;
  user_prompt: string;
  inference_interval: number;
  max_tokens: number;
  mode: 'continuous' | 'triggered';
  trigger_classes: string[];
  trigger_cooldown: number;
  alert_rules: string[];
  sms_enabled: boolean;
  sms_cooldown_seconds: number;
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`
Expected: Errors in VlmPromptEditor.tsx (missing fields in handleApply) — expected, fixed in Task 3.

- [ ] **Step 3: Commit**

```bash
git add react-web/src/types/vlm.ts
git commit -m "feat(sms): add sms_enabled and sms_cooldown_seconds to VlmConfig type"
```

---

## Task 2: Device-side SMS cooldown and publish

**Files:**
- Modify: `greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py`

- [ ] **Step 1: Add SMS state fields to `__init__`**

After line `self.alert_rules = []` (line 54), add:

```python
        self.sms_enabled = False
        self.sms_cooldown_seconds = 300
        self._sms_last_sent = {}
```

- [ ] **Step 2: Add `_publish_to_topic` helper method**

Add after the existing `_publish` method (after line 497):

```python
    def _publish_to_topic(self, topic, payload):
        """Publish a payload to a specific MQTT topic."""
        try:
            encoded = json.dumps(payload).encode("utf-8")
            self.ipc_client.publish_to_iot_core(
                topic_name=topic,
                qos="1",
                payload=encoded,
            )
            logger.info("Published to %s", topic)
        except Exception as e:
            logger.error("Failed to publish to %s: %s", topic, e)
```

- [ ] **Step 3: Add `_maybe_publish_sms_alert` method**

Add after `_publish_to_topic`:

```python
    def _maybe_publish_sms_alert(self, alert, response):
        """Publish to camera/alerts/sms if SMS enabled and cooldown elapsed."""
        if not self.sms_enabled:
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

- [ ] **Step 4: Call `_maybe_publish_sms_alert` for triggered alerts**

In the `_run_inference` method, find the block (around line 369-371):

```python
        if response and self.alert_rules:
            alerts = self._evaluate_alerts(image_b64)
            response["alerts"] = alerts
```

Replace with:

```python
        if response and self.alert_rules:
            alerts = self._evaluate_alerts(image_b64)
            response["alerts"] = alerts
            for alert in alerts:
                if alert.get("triggered"):
                    self._maybe_publish_sms_alert(alert, response)
```

- [ ] **Step 5: Load SMS config in `_load_config`**

After `self.alert_rules = vlm_config.get("alert_rules", [])` (line 165), add:

```python
        self.sms_enabled = vlm_config.get("sms_enabled", False)
        self.sms_cooldown_seconds = int(vlm_config.get("sms_cooldown_seconds", 300))
```

- [ ] **Step 6: Handle SMS config in `_apply_vlm_config`**

After `self.alert_rules = vlm_config["alert_rules"]` (line 194), add:

```python
        if "sms_enabled" in vlm_config:
            self.sms_enabled = bool(vlm_config["sms_enabled"])
        if "sms_cooldown_seconds" in vlm_config:
            self.sms_cooldown_seconds = int(vlm_config["sms_cooldown_seconds"])
```

- [ ] **Step 7: Include SMS fields in `_report_vlm_config`**

In the `_report_vlm_config` method, add to the dict (after `"alert_rules": self.alert_rules,`):

```python
                "sms_enabled": self.sms_enabled,
                "sms_cooldown_seconds": self.sms_cooldown_seconds,
```

- [ ] **Step 8: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py').read())"`

- [ ] **Step 9: Commit**

```bash
git add greengrass-components/artifacts/com.example.VlmInferenceHandler/1.0.0/vlm_handler.py
git commit -m "feat(sms): add SMS cooldown and publish to camera/alerts/sms"
```

---

## Task 3: React UI — SMS toggle and cooldown in Alert Rules section

**Files:**
- Modify: `react-web/src/components/controls/VlmPromptEditor.tsx`
- Modify: `react-web/src/components/controls/VlmPromptEditor.css`

- [ ] **Step 1: Add state for SMS fields in VlmPromptEditor**

In `VlmPromptEditor.tsx`, after `const [alertRules, setAlertRules] = useState<string[]>([]);` (around line 35), add:

```typescript
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [smsCooldownSeconds, setSmsCooldownSeconds] = useState(300);
```

- [ ] **Step 2: Load SMS fields from config**

In the `useEffect` load callback, after `setAlertRules(config.alert_rules);` (around line 54), add:

```typescript
        setSmsEnabled(config.sms_enabled ?? false);
        setSmsCooldownSeconds(config.sms_cooldown_seconds ?? 300);
```

- [ ] **Step 3: Include SMS fields in handleApply**

In `handleApply`, update the `config` object to include the new fields:

```typescript
      const config: VlmConfig = {
        system_prompt: systemPrompt,
        user_prompt: userPrompt,
        inference_interval: inferenceInterval,
        max_tokens: maxTokens,
        mode,
        trigger_classes: triggerClasses,
        trigger_cooldown: triggerCooldown,
        alert_rules: alertRules,
        sms_enabled: smsEnabled,
        sms_cooldown_seconds: smsCooldownSeconds,
      };
```

- [ ] **Step 4: Add SMS controls in the Alert Rules section**

In the JSX, inside the "Alert Rules" section (after the closing `</div>` of `vlm-prompt-editor__alert-rules` and before the section's closing `</section>`), add:

```tsx
        <div className="vlm-prompt-editor__sms-config">
          <div className="vlm-prompt-editor__sms-toggle">
            <label className="vlm-prompt-editor__label">SMS Notifications</label>
            <button
              type="button"
              className={`vlm-prompt-editor__toggle-btn ${smsEnabled ? 'vlm-prompt-editor__toggle-btn--active' : ''}`}
              onClick={() => setSmsEnabled(!smsEnabled)}
              aria-pressed={smsEnabled}
            >
              {smsEnabled ? 'Enabled' : 'Disabled'}
            </button>
          </div>
          {smsEnabled && (
            <div className="vlm-prompt-editor__field">
              <label className="vlm-prompt-editor__label">SMS Cooldown (seconds)</label>
              <input
                type="number"
                className="vlm-prompt-editor__input"
                value={smsCooldownSeconds}
                onChange={(e) => setSmsCooldownSeconds(Math.max(60, parseInt(e.target.value) || 300))}
                min={60}
                max={3600}
              />
              <span className="vlm-prompt-editor__hint">Minimum time between SMS for the same rule</span>
            </div>
          )}
        </div>
```

- [ ] **Step 5: Add CSS for SMS toggle button**

In `VlmPromptEditor.css`, add at the end of the file:

```css
.vlm-prompt-editor__sms-config {
  margin-top: 12px;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.vlm-prompt-editor__sms-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.vlm-prompt-editor__toggle-btn {
  padding: 8px 16px;
  border-radius: 6px;
  border: 2px solid rgba(255, 255, 255, 0.2);
  background: rgba(15, 20, 35, 0.8);
  color: var(--color-text-secondary, #b0bec5);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.vlm-prompt-editor__toggle-btn--active {
  background: rgba(16, 185, 129, 0.25);
  border-color: rgba(16, 185, 129, 0.6);
  color: #ffffff;
}

.vlm-prompt-editor__toggle-btn:hover {
  border-color: rgba(255, 255, 255, 0.35);
}

.vlm-prompt-editor__toggle-btn--active:hover {
  border-color: rgba(16, 185, 129, 0.8);
}
```

- [ ] **Step 6: Verify TypeScript compiles**

Run: `cd react-web && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 7: Commit**

```bash
git add react-web/src/components/controls/VlmPromptEditor.tsx react-web/src/components/controls/VlmPromptEditor.css
git commit -m "feat(sms): add SMS toggle and cooldown controls to Alert Rules UI"
```

---

## Task 4: AWS infrastructure provisioning

**Files:**
- Modify: `scripts/setup_aws_resources.py`

- [ ] **Step 1: Add `setup_sms_alerts` method**

Add after the `setup_hosting` method (before `setup_all`):

```python
    def setup_sms_alerts(self, phone_number):
        """Provision IoT Rule + SNS topic + subscription for SMS alerts."""
        topic_name = f'{self.project_name}-sms-alerts'
        rule_name = f'{self.project_name.replace("-", "_")}_sms_alert_rule'
        role_name = f'{self.project_name}-iot-sns-role'

        print(f"\n{'='*60}")
        print(f"Setting up SMS alert notifications")
        print(f"{'='*60}\n")

        # 1. Create SNS topic
        sns = boto3.client('sns', region_name=self.aws_region)
        topic_resp = sns.create_topic(Name=topic_name)
        topic_arn = topic_resp['TopicArn']
        print(f"SNS topic: {topic_arn}")

        # 2. Subscribe phone number
        sns.subscribe(
            TopicArn=topic_arn,
            Protocol='sms',
            Endpoint=phone_number,
        )
        print(f"SMS subscription: {phone_number}")

        # 3. Create IAM role for IoT → SNS
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "iot.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }
        try:
            self.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=json.dumps(trust_policy),
            )
            print(f"Created IAM role: {role_name}")
        except ClientError as e:
            if e.response['Error']['Code'] in ('EntityAlreadyExists', 'EntityAlreadyExistsException'):
                print(f"IAM role already exists: {role_name}")
            else:
                raise

        sns_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": "sns:Publish",
                "Resource": topic_arn,
            }]
        }
        self.iam.put_role_policy(
            RoleName=role_name,
            PolicyName=f'{role_name}-sns-publish',
            PolicyDocument=json.dumps(sns_policy),
        )
        role_arn = f"arn:aws:iam::{self.account_id}:role/{role_name}"

        # 4. Create IoT Core Rule
        rule_payload = {
            'sql': "SELECT rule, detail, risk_level, thing_name, timestamp FROM 'camera/alerts/sms'",
            'actions': [{
                'sns': {
                    'targetArn': topic_arn,
                    'roleArn': role_arn,
                    'messageFormat': 'RAW',
                }
            }],
            'ruleDisabled': False,
        }
        try:
            self.iot.create_topic_rule(
                ruleName=rule_name,
                topicRulePayload=rule_payload,
            )
            print(f"Created IoT Rule: {rule_name}")
        except ClientError as e:
            if e.response['Error']['Code'] == 'ResourceAlreadyExistsException':
                self.iot.replace_topic_rule(
                    ruleName=rule_name,
                    topicRulePayload=rule_payload,
                )
                print(f"Updated IoT Rule: {rule_name}")
            else:
                raise

        print(f"\n{'='*60}")
        print(f"SMS alerts configured!")
        print(f"Phone: {phone_number}")
        print(f"Topic: camera/alerts/sms → SNS → SMS")
        print(f"{'='*60}\n")
```

- [ ] **Step 2: Add `--stage sms-alerts` and `--sms-phone` to CLI**

In the `main()` function, update the `--stage` choices:

```python
    parser.add_argument('--stage', choices=['setup', 'hosting', 'sms-alerts'], help='Run a specific stage only')
```

Add a new argument after `--hosting-bucket`:

```python
    parser.add_argument('--sms-phone', help='Phone number for SMS alerts (E.164 format, e.g. +447700900123)')
```

Update the stage routing in main() (add before the `else:` block):

```python
        elif args.stage == 'sms-alerts':
            if not args.sms_phone:
                parser.error('--sms-phone is required for sms-alerts stage')
            setup.setup_sms_alerts(args.sms_phone)
```

- [ ] **Step 3: Verify syntax**

Run: `python3 -c "import ast; ast.parse(open('scripts/setup_aws_resources.py').read())"`

- [ ] **Step 4: Verify help shows new options**

Run: `python3 scripts/setup_aws_resources.py --help`
Expected: Shows `--stage {setup,hosting,sms-alerts}` and `--sms-phone` options.

- [ ] **Step 5: Commit**

```bash
git add scripts/setup_aws_resources.py
git commit -m "feat(sms): add setup_sms_alerts for IoT Rule + SNS provisioning"
```

---

## Task 5: End-to-end validation

**Files:**
- No source changes — validation only.

- [ ] **Step 1: Provision SMS infrastructure**

Run:
```bash
python3 scripts/setup_aws_resources.py --stage sms-alerts --region eu-west-1 --sms-phone "+447700900123"
```
Expected: Creates SNS topic, subscription, IAM role, IoT Rule. Prints success message.

- [ ] **Step 2: Re-run to verify idempotency**

Run the same command again.
Expected: No errors, resources already exist messages.

- [ ] **Step 3: Enable SMS in the React UI**

1. Open the dashboard
2. Go to VLM settings panel → Alert Rules section
3. Toggle "SMS Notifications" to Enabled
4. Set cooldown to 60 seconds (for testing)
5. Click Apply

- [ ] **Step 4: Trigger an alert**

Present a scene that triggers a configured alert rule.
Expected:
- AlertBanner fires in the React UI (as before)
- SMS arrives at the configured phone number within ~20 seconds
- No repeat SMS within 60 seconds even if alert keeps triggering

- [ ] **Step 5: Verify cooldown**

Wait for VLM to trigger the same alert again (within 60 seconds).
Expected: No second SMS. After 60 seconds elapses, next trigger sends SMS.
