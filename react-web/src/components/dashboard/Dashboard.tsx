/**
 * Main Dashboard Component - Layout container for authenticated users
 * Redesigned: content-first layout with collapsible settings panel
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { InferenceOverlay } from './InferenceOverlay';
import { EdgeLatencyIndicator } from './EdgeLatencyIndicator';
import { VlmPanel } from './VlmPanel';
import { VlmTimeline } from './VlmTimeline';
import { AlertBanner } from './AlertBanner';
import { SceneQueryPanel } from './SceneQueryPanel';
import { VlmPromptEditor } from '../controls/VlmPromptEditor';
import { useInferenceResults } from '../../hooks/useInferenceResults';
import { useVlmResults } from '../../hooks/useVlmResults';
import { Header } from './Header';
// import { ImageGallery } from './ImageGallery';  // S3 features temporarily hidden
import { MessageFeed } from './MessageFeed';
// import { S3BucketInput } from './S3BucketInput';  // S3 features temporarily hidden
import { MqttTopicInput } from './MqttTopicInput';
import { ThingNameInput } from './ThingNameInput';
import { ConfidenceThresholdControl } from './ConfidenceThresholdControl';
import { InferenceIntervalControl } from './InferenceIntervalControl';
import { ModelSelector } from '../controls/ModelSelector';
import { VlmModelSelector } from '../controls/VlmModelSelector';
import { S3Provider } from '../../contexts/S3Context';
import { MqttProvider, useMqtt } from '../../contexts/MqttContext';
import { useAuthenticatedAWS } from '../../hooks/useAuthenticatedAWS';
import { KvsPlayer } from './KvsPlayer';
import type { AwsCredentialIdentity } from '@aws-sdk/types';
import { config } from '../../utils/config';

// import { S3Object, S3Error } from '../../types/s3';  // S3 features temporarily hidden
import './Dashboard.css';

export interface DashboardProps {
  children?: React.ReactNode;
  className?: string;
}

// Internal Dashboard Content Component that uses S3Context and MqttContext
const DashboardContent: React.FC<DashboardProps> = ({
  children,
  className = '',
}) => {
  const { state: mqttState } = useMqtt();
  const { credentials, region } = useAuthenticatedAWS();
  const [thingName, setThingName] = useState<string>('');
  const [mqttTopic, setMqttTopic] = useState<string>('camera/#');
  const [activeLeftPanel, setActiveLeftPanel] = useState<'general' | 'cv' | 'vlm' | null>(null);
  const [messagePanelOpen, setMessagePanelOpen] = useState<boolean>(false);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const [vlmTab, setVlmTab] = useState<'assessment' | 'query'>('assessment');
  const contentRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!videoElement) return;
    const observer = new ResizeObserver(() => {
      const h = videoElement.getBoundingClientRect().height;
      if (contentRef.current && h > 0) {
        contentRef.current.style.setProperty('--video-height', `${h}px`);
      }
    });
    observer.observe(videoElement);
    return () => observer.disconnect();
  }, [videoElement]);
  const { latestResult } = useInferenceResults();
  const { latestResult: vlmLatestResult, history: vlmHistory, latestAlerts, latestTimestamp } = useVlmResults();

  /**
   * Handle MQTT topic change
   */
  const handleMqttTopicChange = useCallback((topic: string) => {
    setMqttTopic(topic);
  }, []);

  // Determine MQTT status from context
  const getMqttStatus = () => {
    if (mqttState.connected) return 'connected';
    if (mqttState.error) return 'error';
    if (
      mqttState.connectionStatus === 'connecting' ||
      mqttState.connectionStatus === 'reconnecting'
    )
      return 'loading';
    return 'disconnected';
  };

  const mqttStatus = getMqttStatus();

  return (
    <div className={`dashboard ${className}`} role="application" aria-label="Computer Vision Dashboard">
      {/* Header */}
      <Header />

      {/* Main Content Area */}
      <main id="main-content" className="dashboard__main" role="main">
        <div className="dashboard__container">

          {/* Status Bar - always visible, compact */}
          <div className="dashboard__status-bar">
            <div className="dashboard__status-pills" role="status" aria-live="polite" aria-label="Connection status">
              <span className={`dashboard__pill dashboard__pill--success`} aria-label="Auth: Connected">
                <span className="dashboard__pill-dot dashboard__pill-dot--success" aria-hidden="true"></span>
                Auth
              </span>
              <span className={`dashboard__pill dashboard__pill--${mqttStatus === 'connected' ? 'success' : mqttStatus === 'error' ? 'error' : 'pending'}`} aria-label={`MQTT: ${mqttStatus}`}>
                <span className={`dashboard__pill-dot dashboard__pill-dot--${mqttStatus === 'connected' ? 'success' : mqttStatus === 'error' ? 'error' : 'pending'}`} aria-hidden="true"></span>
                MQTT
              </span>
            </div>
            <EdgeLatencyIndicator latestResult={latestResult} videoElement={videoElement} />
          </div>

          {credentials && (
            <>
              <AlertBanner alerts={latestAlerts} timestamp={latestTimestamp} />
              <section ref={contentRef} className="dashboard__content" aria-label="Live video and analysis">
                <article className="dashboard__card dashboard__card--video" style={{ position: 'relative' }}>
                  <KvsPlayer
                    streamName={(import.meta as any).env?.VITE_KVS_STREAM_NAME ?? ''}
                    region={region ?? config.aws.region}
                    credentials={credentials as unknown as AwsCredentialIdentity}
                    onVideoReady={setVideoElement}
                  />
                  <InferenceOverlay result={latestResult} videoElement={videoElement} vlmRiskLevel={vlmLatestResult?.response?.risk_level ?? null} />
                </article>
                <aside className="dashboard__vlm-panel" aria-label="VLM Risk Assessment">
                  <div className="dashboard__vlm-tabs">
                    <button
                      className={`dashboard__vlm-tab ${vlmTab === 'assessment' ? 'dashboard__vlm-tab--active' : ''}`}
                      onClick={() => setVlmTab('assessment')}
                      type="button"
                    >
                      Assessment
                    </button>
                    <button
                      className={`dashboard__vlm-tab ${vlmTab === 'query' ? 'dashboard__vlm-tab--active' : ''}`}
                      onClick={() => setVlmTab('query')}
                      type="button"
                    >
                      Scene Query
                    </button>
                  </div>
                  {vlmTab === 'assessment' && <VlmPanel latestResult={vlmLatestResult} />}
                  {vlmTab === 'query' && <SceneQueryPanel />}
                </aside>
              </section>
              {/* <section className="dashboard__timeline" aria-label="Analysis timeline">
                <VlmTimeline history={vlmHistory} />
              </section> */}
            </>
          )}

          {/* Custom children content */}
          {children && (
            <section className="dashboard__custom">{children}</section>
          )}
        </div>
      </main>

      {/* Left panel tabs */}
      <div className={`dashboard__left-tabs ${activeLeftPanel ? 'dashboard__left-tabs--shifted' : ''}`}>
        <button
          className={`dashboard__drawer-tab dashboard__drawer-tab--left ${activeLeftPanel === 'general' ? 'dashboard__drawer-tab--active' : ''}`}
          onClick={() => setActiveLeftPanel(activeLeftPanel === 'general' ? null : 'general')}
          aria-expanded={activeLeftPanel === 'general'}
          aria-controls="settings-drawer"
          aria-label={activeLeftPanel === 'general' ? 'Hide general settings' : 'Show general settings'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
          <span className="dashboard__drawer-tab-label">General</span>
        </button>
        <button
          className={`dashboard__drawer-tab dashboard__drawer-tab--left dashboard__drawer-tab--cv ${activeLeftPanel === 'cv' ? 'dashboard__drawer-tab--active' : ''}`}
          onClick={() => setActiveLeftPanel(activeLeftPanel === 'cv' ? null : 'cv')}
          aria-expanded={activeLeftPanel === 'cv'}
          aria-controls="settings-drawer"
          aria-label={activeLeftPanel === 'cv' ? 'Hide CV settings' : 'Show CV settings'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <rect x="2" y="2" width="20" height="20" rx="2"></rect>
            <circle cx="8.5" cy="8.5" r="1.5"></circle>
            <polyline points="21 15 16 10 5 21"></polyline>
          </svg>
          <span className="dashboard__drawer-tab-label">CV</span>
        </button>
        <button
          className={`dashboard__drawer-tab dashboard__drawer-tab--left dashboard__drawer-tab--vlm ${activeLeftPanel === 'vlm' ? 'dashboard__drawer-tab--active' : ''}`}
          onClick={() => setActiveLeftPanel(activeLeftPanel === 'vlm' ? null : 'vlm')}
          aria-expanded={activeLeftPanel === 'vlm'}
          aria-controls="settings-drawer"
          aria-label={activeLeftPanel === 'vlm' ? 'Hide VLM settings' : 'Show VLM settings'}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
          </svg>
          <span className="dashboard__drawer-tab-label">VLM</span>
        </button>
      </div>

      <aside
        id="settings-drawer"
        className={`dashboard__drawer dashboard__drawer--left ${activeLeftPanel ? 'dashboard__drawer--open' : ''}`}
        aria-label="Settings"
        aria-hidden={!activeLeftPanel}
      >
        <div className="dashboard__drawer-header">
          <h3 className="dashboard__drawer-title">
            {activeLeftPanel === 'general' && 'General Settings'}
            {activeLeftPanel === 'cv' && 'CV Inference'}
            {activeLeftPanel === 'vlm' && 'VLM Controls'}
          </h3>
          <button
            className="dashboard__drawer-close"
            onClick={() => setActiveLeftPanel(null)}
            aria-label="Close settings panel"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div className="dashboard__drawer-content">
          <div className={`dashboard__panel-page ${activeLeftPanel === 'general' ? 'dashboard__panel-page--active' : ''}`}>
            <div className="dashboard__settings-section">
              <div className="dashboard__settings-stack">
                <MqttTopicInput
                  className="dashboard__settings-field"
                  topic={mqttTopic}
                  onTopicChange={handleMqttTopicChange}
                />
                <ThingNameInput
                  className="dashboard__settings-field"
                  thingName={thingName}
                  onThingNameChange={setThingName}
                />
              </div>
            </div>
          </div>
          <div className={`dashboard__panel-page ${activeLeftPanel === 'cv' ? 'dashboard__panel-page--active' : ''}`}>
            <div className="dashboard__settings-section">
              {!thingName && (
                <p className="dashboard__panel-hint">Set an IoT Thing Name in General settings to enable these controls.</p>
              )}
              <div className="dashboard__settings-stack">
                <div className="dashboard__settings-field">
                  <ConfidenceThresholdControl thingName={thingName} />
                </div>
                <div className="dashboard__settings-field">
                  <InferenceIntervalControl thingName={thingName} />
                </div>
                <div className="dashboard__settings-field">
                  <ModelSelector thingName={thingName} />
                </div>
              </div>
            </div>
          </div>
          <div className={`dashboard__panel-page ${activeLeftPanel === 'vlm' ? 'dashboard__panel-page--active' : ''}`}>
            <div className="dashboard__settings-section">
              {!thingName && (
                <p className="dashboard__panel-hint">Set an IoT Thing Name in General settings to enable these controls.</p>
              )}
              <div className="dashboard__settings-stack">
                <div className="dashboard__settings-field">
                  <VlmModelSelector thingName={thingName} />
                </div>
                <VlmPromptEditor thingName={thingName} />
              </div>
            </div>
          </div>
        </div>
      </aside>

      {/* IoT Message Feed - slide-out panel from right */}
      <button
        className={`dashboard__drawer-tab ${messagePanelOpen ? 'dashboard__drawer-tab--active' : ''}`}
        onClick={() => setMessagePanelOpen(!messagePanelOpen)}
        aria-expanded={messagePanelOpen}
        aria-controls="message-drawer"
        aria-label={messagePanelOpen ? 'Hide messages' : 'Show messages'}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span className="dashboard__drawer-tab-label">Messages</span>
        {mqttState.messageCount > 0 && (
          <span className="dashboard__drawer-tab-badge">{mqttState.messageCount}</span>
        )}
      </button>

      <aside
        id="message-drawer"
        className={`dashboard__drawer ${messagePanelOpen ? 'dashboard__drawer--open' : ''}`}
        aria-label="IoT Message Feed"
        aria-hidden={!messagePanelOpen}
      >
        <div className="dashboard__drawer-header">
          <h3 className="dashboard__drawer-title">IoT Messages</h3>
          <button
            className="dashboard__drawer-close"
            onClick={() => setMessagePanelOpen(false)}
            aria-label="Close message panel"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        <div className="dashboard__drawer-content">
          <MessageFeed
            className="dashboard__message-feed"
            maxMessages={50}
            showConnectionStatus={true}
          />
        </div>
      </aside>
    </div>
  );
};

// Main Dashboard Component that provides S3Context and MqttContext
export const Dashboard: React.FC<DashboardProps> = ({ children, className }) => {
  return (
    <S3Provider autoRefreshInterval={30000} maxImages={20}>
      <MqttProvider autoConnect={true} defaultTopic="camera/#">
        <DashboardContent children={children} className={className} />
      </MqttProvider>
    </S3Provider>
  );
};
