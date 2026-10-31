import { useState, useEffect } from 'react';
import { getInitialAppTab, type AppTab } from '../navigation.ts';
import { useBackgroundMetadataJobs } from './useBackgroundMetadataJobs.ts';

export function useAppShellState() {
  const [activeTab, setActiveTab] = useState<AppTab>(getInitialAppTab);
  // Treat the app's sections as browser-history states. Android back buttons
  // and swipe-back gestures therefore move from Files/other sections to Search
  // instead of immediately leaving the web app. Once already on Search, the
  // next Back is allowed to leave the page normally.
  useEffect(() => {
    const currentState = window.history.state;
    if (!currentState?.torrentStudio) {
      window.history.replaceState(
        { ...(currentState || {}), torrentStudio: true, tab: activeTab },
        '',
        window.location.href
      );
      return;
    }

    if (currentState.tab !== activeTab) {
      window.history.pushState(
        { ...currentState, torrentStudio: true, tab: activeTab },
        '',
        window.location.href
      );
    }
  }, [activeTab]);
  useEffect(() => {
    const handlePopState = () => {
      const stateTab = window.history.state?.torrentStudio
        ? window.history.state.tab
        : null;

      if (
        stateTab === 'search' ||
        stateTab === 'files' ||
        stateTab === 'shared' ||
        stateTab === 'activity' ||
        stateTab === 'storage'
      ) {
        setActiveTab(stateTab);
      }
    };

    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, [activeTab]);
  const { backgroundMetadataJob, setBackgroundMetadataJob } = useBackgroundMetadataJobs();
  const [initialSourceUrl, setInitialSourceUrl] = useState('');
  const [initialDescriptorUrl, setInitialDescriptorUrl] = useState('');
  const [theme, setTheme] = useState<'dark' | 'dim'>(() => {
    try {
      const saved = window.localStorage.getItem('seedflow_theme');
      return saved === 'dim' ? 'dim' : 'dark';
    } catch {
      return 'dark';
    }
  });

  return {
    activeTab,
    setActiveTab,
    backgroundMetadataJob,
    setBackgroundMetadataJob,
    initialSourceUrl,
    setInitialSourceUrl,
    initialDescriptorUrl,
    setInitialDescriptorUrl,
    theme,
    setTheme,
  };
}
