/**
 * Main Dashboard Component - Layout container for authenticated users
 * Redesigned: content-first layout with collapsible settings panel
 */

import React, { useCallback, useState } from 'react';
import { InferenceOverlay } from './InferenceOverlay';
import { InferencePanel } from './InferencePanel';
import { useInferenceResults } from '../../hooks/useInferenceResults';
import { Header } from './Header';
// import { ImageGallery } from './ImageGallery';  // S3 features temporarily hidden
import { MessageFeed } from './MessageFeed';
// import { S3BucketInput } from './S3BucketInput';  // S3 features temporarily hidden
import { MqttTopicInput } from './MqttTopicInput';
import { ThingNameInput } from './ThingNameInput';
import { ConfidenceThresholdControl } from './ConfidenceThresholdControl';
import { ModelSelector } from '../controls/ModelSelector';
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
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);
  const [messagePanelOpen, setMessagePanelOpen] = useState<boolean>(false);
  const [videoElement, setVideoElement] = useState<HTMLVideoElement | null>(null);
  const { latestResult, history } = useInferenceResults();

  /**
   * Handle MQTT topic change
   */
  const handleMqttTopicChange = useCallback((topic: string) => {
    console.log('MQTT topic changed:', topic);
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

            <button
              className={`dashboard__settings-toggle ${settingsOpen ? 'dashboard__settings-toggle--active' : ''}`}
              onClick={() => setSettingsOpen(!settingsOpen)}
              aria-expanded={settingsOpen}
              aria-controls="settings-panel"
              aria-label={settingsOpen ? 'Hide settings' : 'Show settings'}
            >
              <svg className="dashboard__settings-icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <circle cx="12" cy="12" r="3"></circle>
                <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
              </svg>
              Settings
            </button>
          </div>

          {/* Collapsible Settings Panel */}
          <div
            id="settings-panel"
            className={`dashboard__settings-panel ${settingsOpen ? 'dashboard__settings-panel--open' : ''}`}
            role="region"
            aria-labelledby="config-title"
            aria-hidden={!settingsOpen}
          >
            <div className="dashboard__settings-inner">
              <div className="dashboard__settings-section">
                <h3 className="dashboard__settings-heading">Data Sources</h3>
                <div className="dashboard__settings-grid">
                  <MqttTopicInput
                    className="dashboard__settings-field"
                    onTopicChange={handleMqttTopicChange}
                  />
                  <ThingNameInput
                    className="dashboard__settings-field"
                    thingName={thingName}
                    onThingNameChange={setThingName}
                  />
                </div>
              </div>
              <div className="dashboard__settings-section">
                <h3 className="dashboard__settings-heading">Inference Controls</h3>
                <div className="dashboard__settings-grid">
                  <div className="dashboard__settings-field">
                    <ConfidenceThresholdControl thingName={thingName} />
                  </div>
                  <div className="dashboard__settings-field">
                    <ModelSelector thingName={thingName} />
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* KVS Live Stream - primary content */}
          {credentials && (
            <section className="dashboard__content" aria-label="Live video stream">
              <article className="dashboard__card dashboard__card--video" aria-labelledby="video-stream-title" style={{ position: 'relative' }}>
                <KvsPlayer
                  streamName={(import.meta as any).env?.VITE_KVS_STREAM_NAME ?? ''}
                  region={region ?? config.aws.region}
                  credentials={credentials as unknown as AwsCredentialIdentity}
                  onVideoReady={setVideoElement}
                />
                <InferenceOverlay result={latestResult} videoElement={videoElement} />
              </article>
              <InferencePanel latestResult={latestResult} history={history} />
            </section>
          )}

          {/* Custom children content */}
          {children && (
            <section className="dashboard__custom">{children}</section>
          )}
        </div>
      </main>

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
      <MqttProvider autoConnect={false} defaultTopic="camera/inference">
        <DashboardContent children={children} className={className} />
      </MqttProvider>
    </S3Provider>
  );
};
