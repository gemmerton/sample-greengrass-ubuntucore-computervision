/**
 * Main Dashboard Component - Layout container for authenticated users
 * Redesigned: content-first layout with collapsible settings panel
 */

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Header } from './Header';
import { ImageGallery } from './ImageGallery';
import { MessageFeed } from './MessageFeed';
import { S3BucketInput } from './S3BucketInput';
import { MqttTopicInput } from './MqttTopicInput';
import { ThingNameInput } from './ThingNameInput';
import { ConfidenceThresholdControl } from './ConfidenceThresholdControl';
import { ModelSelector } from '../controls/ModelSelector';
import { S3Provider, useS3 } from '../../contexts/S3Context';
import { MqttProvider, useMqtt } from '../../contexts/MqttContext';

import { S3Object, S3Error } from '../../types/s3';
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
  const { state, actions: s3Actions } = useS3();
  const { state: mqttState } = useMqtt();
  const previousMessageCountRef = useRef<number>(0);
  const [thingName, setThingName] = useState<string>('');
  const [settingsOpen, setSettingsOpen] = useState<boolean>(false);

  /**
   * Handle S3 image gallery errors
   */
  const handleS3Error = useCallback((error: S3Error) => {
    console.error('S3 Gallery Error:', error);
  }, []);

  /**
   * Handle successful S3 image load
   */
  const handleImageClick = useCallback((image: S3Object) => {
    console.log('Image clicked:', image);
  }, []);

  /**
   * Handle MQTT topic change
   */
  const handleMqttTopicChange = useCallback((topic: string) => {
    console.log('MQTT topic changed:', topic);
  }, []);

  // Determine S3 status from context
  const getS3Status = () => {
    if (state.loading) return 'loading';
    if (state.error) return 'error';
    if (state.images.length > 0 || state.selectedBucket) return 'connected';
    return 'loading';
  };

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

  /**
   * Auto-refresh S3 images when new MQTT messages are received
   */
  useEffect(() => {
    if (mqttState.messageCount > previousMessageCountRef.current && 
        mqttState.messageCount > 0 && 
        state.selectedBucket && 
        !state.loading) {
      
      console.log(` New MQTT message received (count: ${mqttState.messageCount}), refreshing S3 images...`);
      
      const refreshTimeout = setTimeout(() => {
        s3Actions.refreshImages();
      }, 1000);

      previousMessageCountRef.current = mqttState.messageCount;
      return () => clearTimeout(refreshTimeout);
    } else {
      previousMessageCountRef.current = mqttState.messageCount;
    }
  }, [mqttState.messageCount, state.selectedBucket, state.loading, s3Actions]);

  const s3Status = getS3Status();
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
              <span className={`dashboard__pill dashboard__pill--${s3Status === 'connected' ? 'success' : s3Status === 'error' ? 'error' : 'pending'}`} aria-label={`S3: ${s3Status}`}>
                <span className={`dashboard__pill-dot dashboard__pill-dot--${s3Status === 'connected' ? 'success' : s3Status === 'error' ? 'error' : 'pending'}`} aria-hidden="true"></span>
                S3
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
                  <S3BucketInput className="dashboard__settings-field" />
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

          {/* Content Grid - the hero of the page */}
          <section className="dashboard__content" aria-label="Dashboard content">
            <div className="dashboard__grid">
              {/* S3 Image Gallery */}
              <article className="dashboard__card dashboard__card--images" aria-labelledby="image-gallery-title">
                <ImageGallery
                  className="dashboard__image-gallery"
                  onImageClick={handleImageClick}
                  onError={handleS3Error}
                />
              </article>

              {/* MQTT Message Feed */}
              <article className="dashboard__card dashboard__card--messages" aria-labelledby="message-feed-title">
                <MessageFeed
                  className="dashboard__message-feed"
                  maxMessages={50}
                  showConnectionStatus={true}
                />
              </article>
            </div>
          </section>

          {/* Custom children content */}
          {children && (
            <section className="dashboard__custom">{children}</section>
          )}
        </div>
      </main>
    </div>
  );
};

// Main Dashboard Component that provides S3Context and MqttContext
export const Dashboard: React.FC<DashboardProps> = ({ children, className }) => {
  return (
    <S3Provider autoRefreshInterval={30000} maxImages={20}>
      <MqttProvider autoConnect={false}>
        <DashboardContent children={children} className={className} />
      </MqttProvider>
    </S3Provider>
  );
};
