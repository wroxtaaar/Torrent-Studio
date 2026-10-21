import { useState } from 'react';

export function useSeedrConnectionState() {
  // Navigation & Theme
  // Seedr is connected per browser session using the user's Personal Access Token.
  // The PAT is sent only to our backend over HTTPS and is never stored in localStorage.
  const [productWelcomeOpen, setProductWelcomeOpen] = useState(() => {
    try {
      return window.localStorage.getItem('torrent_studio_welcome_seen') !== 'true';
    } catch {
      return true;
    }
  });
  // Seedr connection is optional. Never open the connection dialog automatically
  // on page load/refresh; the user opens it explicitly or reaches a Seedr action.
  const [seedrOnboardingOpen, setSeedrOnboardingOpen] = useState(false);
  const seedrOnboardingSeenKey = 'seedflow_seedr_onboarding_seen';
  const [seedrConnected, setSeedrConnected] = useState(false);
  const [seedrSessionReady, setSeedrSessionReady] = useState(false);
  const [seedrPat, setSeedrPat] = useState('');
  const [seedrPatSubmitting, setSeedrPatSubmitting] = useState(false);
  const [seedrConnectError, setSeedrConnectError] = useState('');
  const [seedrConfigured, setSeedrConfigured] = useState(false);

  return {
    productWelcomeOpen,
    setProductWelcomeOpen,
    seedrOnboardingOpen,
    setSeedrOnboardingOpen,
    seedrOnboardingSeenKey,
    seedrConnected,
    setSeedrConnected,
    seedrSessionReady,
    setSeedrSessionReady,
    seedrPat,
    setSeedrPat,
    seedrPatSubmitting,
    setSeedrPatSubmitting,
    seedrConnectError,
    setSeedrConnectError,
    seedrConfigured,
    setSeedrConfigured,
  };
}
