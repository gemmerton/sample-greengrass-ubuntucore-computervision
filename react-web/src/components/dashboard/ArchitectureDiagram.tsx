import React, { useState } from 'react';
import './ArchitectureDiagram.css';

interface ArchitectureDiagramProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ArchitectureDiagram: React.FC<ArchitectureDiagramProps> = ({ isOpen, onClose }) => {
  const [view, setView] = useState<'high-level' | 'detailed'>('high-level');

  if (!isOpen) return null;

  return (
    <div className="arch-diagram__backdrop" onClick={onClose}>
      <div className="arch-diagram__modal" onClick={(e) => e.stopPropagation()}>
        <div className="arch-diagram__header">
          <div className="arch-diagram__tabs">
            <button
              className={`arch-diagram__tab ${view === 'high-level' ? 'arch-diagram__tab--active' : ''}`}
              onClick={() => setView('high-level')}
            >
              High Level
            </button>
            <button
              className={`arch-diagram__tab ${view === 'detailed' ? 'arch-diagram__tab--active' : ''}`}
              onClick={() => setView('detailed')}
            >
              Detailed
            </button>
          </div>
          <button className="arch-diagram__close" onClick={onClose}>
            &times;
          </button>
        </div>
        <div className="arch-diagram__content">
          {view === 'high-level' ? <HighLevelView /> : <DetailedView />}
        </div>
      </div>
    </div>
  );
};

const HighLevelView: React.FC = () => (
  <div className="arch-hl">
    <svg className="arch-hl__svg" viewBox="0 0 1600 720" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arrow-green" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#10b981" />
        </marker>
        <marker id="arrow-green-rev" markerWidth="10" markerHeight="7" refX="0" refY="3.5" orient="auto">
          <polygon points="10 0, 0 3.5, 10 7" fill="#10b981" />
        </marker>
        <marker id="arrow-orange" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#ff9900" />
        </marker>
        <marker id="arrow-blue" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#6366f1" />
        </marker>
        <marker id="arrow-blue-rev" markerWidth="10" markerHeight="7" refX="0" refY="3.5" orient="auto">
          <polygon points="10 0, 0 3.5, 10 7" fill="#6366f1" />
        </marker>
        <marker id="arrow-teal" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#6ee7b7" />
        </marker>
        <marker id="arrow-pink" markerWidth="10" markerHeight="7" refX="10" refY="3.5" orient="auto">
          <polygon points="0 0, 10 3.5, 0 7" fill="#f9a8d4" />
        </marker>
      </defs>

      {/* ===== EDGE DEVICE ===== */}
      <rect x="30" y="20" width="550" height="660" rx="16" fill="rgba(16,185,129,0.04)" stroke="rgba(16,185,129,0.3)" strokeWidth="2.5" />
      {/* Note: Camera box extends to y660, outer box bottom at y680 */}
      <text x="305" y="62" textAnchor="middle" fill="#e2e8f0" fontSize="26" fontWeight="bold">Edge Device</text>
      <text x="305" y="90" textAnchor="middle" fill="#94a3b8" fontSize="16">Ubuntu Core + AWS IoT Greengrass</text>

      {/* CV Models box - TOP */}
      <rect x="60" y="110" width="235" height="140" rx="12" fill="rgba(139,92,246,0.08)" stroke="rgba(139,92,246,0.3)" strokeWidth="2" />
      <text x="177" y="150" textAnchor="middle" fill="#c4b5fd" fontSize="20" fontWeight="bold">CV Models</text>
      <text x="177" y="180" textAnchor="middle" fill="#94a3b8" fontSize="15">OpenVINO Model Server</text>
      <text x="177" y="205" textAnchor="middle" fill="#94a3b8" fontSize="15">gRPC :9000</text>
      <text x="177" y="235" textAnchor="middle" fill="#c4b5fd" fontSize="13">One active model at a time</text>

      {/* VLM Models box - shifted down */}
      <rect x="320" y="170" width="230" height="140" rx="12" fill="rgba(236,72,153,0.08)" stroke="rgba(236,72,153,0.3)" strokeWidth="2" />
      <text x="435" y="210" textAnchor="middle" fill="#f9a8d4" fontSize="20" fontWeight="bold">VLM Models</text>
      <text x="435" y="240" textAnchor="middle" fill="#94a3b8" fontSize="15">Standalone Inference Snaps</text>
      <text x="435" y="265" textAnchor="middle" fill="#94a3b8" fontSize="15">HTTP :9090</text>
      <text x="435" y="295" textAnchor="middle" fill="#f9a8d4" fontSize="13">One active snap at a time</text>

      {/* Greengrass Components - shifted down */}
      <rect x="60" y="365" width="490" height="160" rx="12" fill="rgba(16,185,129,0.1)" stroke="rgba(16,185,129,0.35)" strokeWidth="2" />
      <text x="305" y="405" textAnchor="middle" fill="#6ee7b7" fontSize="21" fontWeight="bold">Greengrass Components</text>
      <text x="305" y="437" textAnchor="middle" fill="#94a3b8" fontSize="15">ModelManagerCore &bull; InferenceHandler &bull; VlmHandler</text>
      <text x="305" y="465" textAnchor="middle" fill="#94a3b8" fontSize="15">VlmModelManager &bull; KvsProducer</text>
      <text x="305" y="500" textAnchor="middle" fill="#6ee7b7" fontSize="14">Orchestrates model lifecycle via shadow deltas</text>

      {/* Arrows: Greengrass -> CV Models (upward) */}
      <line x1="177" y1="365" x2="177" y2="252" stroke="#6ee7b7" strokeWidth="2.5" markerEnd="url(#arrow-teal)" />
      {/* Arrows: Greengrass -> VLM Models (upward) */}
      <line x1="435" y1="365" x2="435" y2="312" stroke="#6ee7b7" strokeWidth="2.5" markerEnd="url(#arrow-teal)" />

      {/* Camera box - shifted down */}
      <rect x="140" y="580" width="330" height="80" rx="12" fill="rgba(245,158,11,0.08)" stroke="rgba(245,158,11,0.25)" strokeWidth="2" />
      <text x="305" y="617" textAnchor="middle" fill="#fcd34d" fontSize="20" fontWeight="bold">Camera</text>
      <text x="305" y="645" textAnchor="middle" fill="#94a3b8" fontSize="15">USB/IP Video Feed</text>

      {/* Arrow: Camera -> Greengrass */}
      <line x1="305" y1="578" x2="305" y2="528" stroke="#f59e0b" strokeWidth="2" strokeDasharray="6 4" markerEnd="url(#arrow-orange)" />

      {/* ===== AWS CLOUD ===== */}
      <rect x="820" y="20" width="500" height="380" rx="16" fill="rgba(99,102,241,0.04)" stroke="rgba(99,102,241,0.3)" strokeWidth="2.5" />
      <text x="1070" y="62" textAnchor="middle" fill="#e2e8f0" fontSize="26" fontWeight="bold">AWS Cloud</text>

      {/* S3 box - TOP */}
      <rect x="860" y="85" width="195" height="90" rx="12" fill="rgba(99,102,241,0.1)" stroke="rgba(99,102,241,0.35)" strokeWidth="2" />
      <text x="957" y="125" textAnchor="middle" fill="#a5b4fc" fontSize="20" fontWeight="bold">S3</text>
      <text x="957" y="155" textAnchor="middle" fill="#94a3b8" fontSize="15">Model artefacts</text>

      {/* SNS box - TOP */}
      <rect x="1090" y="85" width="195" height="90" rx="12" fill="rgba(99,102,241,0.1)" stroke="rgba(99,102,241,0.35)" strokeWidth="2" />
      <text x="1187" y="125" textAnchor="middle" fill="#a5b4fc" fontSize="20" fontWeight="bold">SNS</text>
      <text x="1187" y="155" textAnchor="middle" fill="#94a3b8" fontSize="15">SMS Alerts</text>

      {/* IoT Core box - BELOW S3/SNS */}
      <rect x="860" y="220" width="420" height="150" rx="12" fill="rgba(99,102,241,0.1)" stroke="rgba(99,102,241,0.35)" strokeWidth="2" />
      <text x="1070" y="262" textAnchor="middle" fill="#a5b4fc" fontSize="21" fontWeight="bold">IoT Core</text>
      <text x="1070" y="294" textAnchor="middle" fill="#94a3b8" fontSize="15">Named Shadows (model-config, vlm-config)</text>
      <text x="1070" y="322" textAnchor="middle" fill="#94a3b8" fontSize="15">MQTT Broker</text>
      <text x="1070" y="355" textAnchor="middle" fill="#a5b4fc" fontSize="14">Desired/Reported state drives behaviour</text>

      {/* ===== WORKSTATION ===== */}
      <rect x="820" y="490" width="500" height="190" rx="16" fill="rgba(255,153,0,0.04)" stroke="rgba(255,153,0,0.25)" strokeWidth="2.5" />
      <text x="1070" y="532" textAnchor="middle" fill="#e2e8f0" fontSize="26" fontWeight="bold">Workstation / Browser</text>

      {/* Web UI box */}
      <rect x="900" y="555" width="340" height="95" rx="12" fill="rgba(255,153,0,0.08)" stroke="rgba(255,153,0,0.3)" strokeWidth="2" />
      <text x="1070" y="595" textAnchor="middle" fill="#fbbf24" fontSize="20" fontWeight="bold">Web UI</text>
      <text x="1070" y="625" textAnchor="middle" fill="#94a3b8" fontSize="15">Dashboard, model switching, alerts</text>

      {/* ===== CONNECTORS ===== */}

      {/* Shadow Sync: Greengrass <-> IoT Core */}
      <text x="700" y="325" textAnchor="middle" fill="#10b981" fontSize="15" fontWeight="bold">Shadow Sync</text>
      <line x1="550" y1="400" x2="858" y2="295" stroke="#10b981" strokeWidth="3" markerEnd="url(#arrow-green)" markerStart="url(#arrow-green-rev)" />

      {/* MQTT Results: Greengrass -> IoT Core */}
      <text x="700" y="445" textAnchor="middle" fill="#6ee7b7" fontSize="15" fontWeight="bold">MQTT Results</text>
      <line x1="550" y1="450" x2="858" y2="345" stroke="#6ee7b7" strokeWidth="2.5" markerEnd="url(#arrow-teal)" />

      {/* Model Delivery: S3 -> CV Models — straight horizontal at y=130, above VLM box */}
      <text x="680" y="162" textAnchor="middle" fill="#ff9900" fontSize="15" fontWeight="bold">Model Delivery</text>
      <path d="M 860 135 L 297 135" fill="none" stroke="#ff9900" strokeWidth="2.5" strokeDasharray="8 5" markerEnd="url(#arrow-orange)" />

      {/* Model Delivery: S3 -> VLM Models — route down then left, entering VLM from right */}
      <path d="M 860 155 L 750 155 L 750 240 L 552 240" fill="none" stroke="#ff9900" strokeWidth="2.5" strokeDasharray="8 5" markerEnd="url(#arrow-orange)" />

      {/* Web UI <-> IoT Core — vertical, connecting to Workstation box */}
      <text x="1150" y="435" textAnchor="middle" fill="#a5b4fc" fontSize="15" fontWeight="bold">Shadow + MQTT</text>
      <line x1="1070" y1="490" x2="1070" y2="372" stroke="#6366f1" strokeWidth="3" markerEnd="url(#arrow-blue)" markerStart="url(#arrow-blue-rev)" />

      {/* IoT Core -> SNS (upward) */}
      <line x1="1187" y1="220" x2="1187" y2="177" stroke="rgba(165,180,252,0.5)" strokeWidth="2" markerEnd="url(#arrow-blue)" />

      {/* Mobile box (beside Workstation box) */}
      <rect x="1350" y="540" width="200" height="120" rx="16" fill="rgba(236,72,153,0.04)" stroke="rgba(236,72,153,0.3)" strokeWidth="2.5" />
      <text x="1450" y="590" textAnchor="middle" fill="#e2e8f0" fontSize="22" fontWeight="bold">Mobile</text>
      <text x="1450" y="620" textAnchor="middle" fill="#94a3b8" fontSize="14">SMS Alerts</text>
      {/* Arrow: SNS -> Mobile, route right out of SNS box then down */}
      <path d="M 1285 130 L 1450 130 L 1450 538" fill="none" stroke="#f9a8d4" strokeWidth="2.5" markerEnd="url(#arrow-pink)" />
    </svg>

    {/* Flow description */}
    <div className="arch-hl__flow">
      <p><strong>Model Switch Flow:</strong> Web UI updates shadow desired state &rarr; IoT Core delivers delta to edge &rarr; ModelManager orchestrates switch &rarr; new model serves inference &rarr; results flow back via MQTT</p>
    </div>
  </div>
);

const DetailedView: React.FC = () => (
  <div className="arch-detail">
    <div className="arch-detail__row">
      {/* Edge Device - Expanded */}
      <div className="arch-block arch-block--edge arch-block--expanded">
        <div className="arch-block__label">Edge Device — Ubuntu Core</div>

        {/* Greengrass Components */}
        <div className="arch-detail__section">
          <div className="arch-detail__section-title">AWS IoT Greengrass</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--gg">ModelManagerCore</div>
            <div className="arch-chip arch-chip--gg">InferenceHandler</div>
            <div className="arch-chip arch-chip--gg">VlmInferenceHandler</div>
            <div className="arch-chip arch-chip--gg">VlmModelManager</div>
            <div className="arch-chip arch-chip--gg">KvsProducer</div>
          </div>
        </div>

        {/* OVMS + CV Models */}
        <div className="arch-detail__section">
          <div className="arch-detail__section-title">ovms-engine snap (gRPC :9000)</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--model">person-detection</div>
            <div className="arch-chip arch-chip--model">faster-rcnn</div>
            <div className="arch-chip arch-chip--model">yolov8s</div>
            <div className="arch-chip arch-chip--model">yolo26pose</div>
          </div>
          <div className="arch-detail__note">One active at a time, switched via shadow</div>
        </div>

        {/* VLM Snaps */}
        <div className="arch-detail__section">
          <div className="arch-detail__section-title">VLM Inference Snaps (HTTP :9090)</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--vlm">gemma3</div>
            <div className="arch-chip arch-chip--vlm">qwen-vl</div>
            <div className="arch-chip arch-chip--vlm">internvl2</div>
          </div>
          <div className="arch-detail__note">Standalone snaps, one active at a time</div>
        </div>

        {/* Internal connections */}
        <div className="arch-detail__connections">
          <div className="arch-detail__conn">
            <span className="arch-detail__conn-from">InferenceHandler</span>
            <span className="arch-detail__conn-arrow">&rarr;</span>
            <span className="arch-detail__conn-to">OVMS (gRPC)</span>
          </div>
          <div className="arch-detail__conn">
            <span className="arch-detail__conn-from">VlmInferenceHandler</span>
            <span className="arch-detail__conn-arrow">&rarr;</span>
            <span className="arch-detail__conn-to">VLM Snap (HTTP)</span>
          </div>
          <div className="arch-detail__conn">
            <span className="arch-detail__conn-from">ModelManagerCore</span>
            <span className="arch-detail__conn-arrow">&rarr;</span>
            <span className="arch-detail__conn-to">ovms-engine (snap component install)</span>
          </div>
          <div className="arch-detail__conn">
            <span className="arch-detail__conn-from">VlmModelManager</span>
            <span className="arch-detail__conn-arrow">&rarr;</span>
            <span className="arch-detail__conn-to">VLM Snaps (snap install/start/stop)</span>
          </div>
        </div>
      </div>

      {/* Cloud - focused on shadows */}
      <div className="arch-block arch-block--cloud arch-block--expanded">
        <div className="arch-block__label">AWS IoT Core</div>

        <div className="arch-detail__section">
          <div className="arch-detail__section-title">Named Shadows (Device Twin)</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--shadow">model-config</div>
            <div className="arch-chip arch-chip--shadow">vlm-config</div>
            <div className="arch-chip arch-chip--shadow">inference-config</div>
            <div className="arch-chip arch-chip--shadow">kvs-config</div>
          </div>
          <div className="arch-detail__note">Desired state drives device behaviour; reported state reflects actual</div>
        </div>

        <div className="arch-detail__section">
          <div className="arch-detail__section-title">MQTT Topics</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--topic">camera/inference</div>
            <div className="arch-chip arch-chip--topic">camera/vlm</div>
            <div className="arch-chip arch-chip--topic">camera/alerts/sms</div>
          </div>
        </div>

        <div className="arch-detail__section">
          <div className="arch-detail__section-title">Supporting Services</div>
          <div className="arch-detail__components">
            <div className="arch-chip arch-chip--service">S3 (model artefacts)</div>
            <div className="arch-chip arch-chip--service">SNS (SMS alerts)</div>
            <div className="arch-chip arch-chip--service">KVS (video stream)</div>
          </div>
        </div>
      </div>
    </div>

    {/* Web UI */}
    <div className="arch-detail__bottom">
      <div className="arch-block arch-block--ui">
        <div className="arch-block__label">Web UI</div>
        <div className="arch-block__detail">Reads shadows for model state, writes desired state for switching, subscribes to MQTT for live results</div>
      </div>
    </div>

    {/* Key flows */}
    <div className="arch-detail__flows">
      <div className="arch-detail__flow-item">
        <strong>CV Model Switch:</strong> Web UI &rarr; shadow desired (model-config.active_model) &rarr; delta &rarr; ModelManagerCore &rarr; OVMS reconfigured
      </div>
      <div className="arch-detail__flow-item">
        <strong>VLM Model Switch:</strong> Web UI &rarr; shadow desired (vlm-config.active_model) &rarr; delta &rarr; VlmModelManager &rarr; snap start/stop
      </div>
      <div className="arch-detail__flow-item">
        <strong>SMS Alert:</strong> VlmInferenceHandler detects alert rule match &rarr; publishes to camera/alerts/sms &rarr; IoT Rule &rarr; SNS &rarr; SMS
      </div>
    </div>
  </div>
);
