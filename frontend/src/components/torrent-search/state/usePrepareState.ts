import { useRef, useState } from 'react';
import { SeedrSearchFile } from '../props.ts';

export function usePrepareState() {
  const [preparingTorrentKey, setPreparingTorrentKey] = useState<string | null>(null);
  const [playingTorrentKey, setPlayingTorrentKey] = useState<string | null>(null);
  const [copiedTorrentKey, setCopiedTorrentKey] = useState<string | null>(null);
  const [prepareWaitTitle, setPrepareWaitTitle] = useState('');
  const [prepareWaitOpen, setPrepareWaitOpen] = useState(false);
  const [prepareError, setPrepareError] = useState('');
  const [fullTorrentTitle, setFullTorrentTitle] = useState<string | null>(null);
  const [fullTorrentTitleKey, setFullTorrentTitleKey] = useState<string | null>(null);
  const [fullTorrentTitleFading, setFullTorrentTitleFading] = useState(false);
  const fullTorrentTitleFadeTimerRef = useRef<number | null>(null);
  const fullTorrentTitleHideTimerRef = useRef<number | null>(null);
  const preparedByKeyRef = useRef(new Map<string, { files: SeedrSearchFile[] }>());

  return {
    preparingTorrentKey,
    setPreparingTorrentKey,
    playingTorrentKey,
    setPlayingTorrentKey,
    copiedTorrentKey,
    setCopiedTorrentKey,
    prepareWaitTitle,
    setPrepareWaitTitle,
    prepareWaitOpen,
    setPrepareWaitOpen,
    prepareError,
    setPrepareError,
    setFullTorrentTitle,
    setFullTorrentTitleKey,
    setFullTorrentTitleFading,
    fullTorrentTitleFadeTimerRef,
    fullTorrentTitleHideTimerRef,
    preparedByKeyRef,
  };
}
