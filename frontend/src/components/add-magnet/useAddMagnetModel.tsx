import React, { useState, useEffect, useRef } from 'react';
import { api } from '../../api/client.ts';
import type { AddMagnetModalProps, InspectFileItem } from './types.ts';

export function useAddMagnetModel(props: AddMagnetModalProps & Required<Pick<AddMagnetModalProps, 'defaultFolder' | 'initialMagnet' | 'initialSourceUrl' | 'initialDescriptorUrl'>>) {
  const { defaultFolder, isOpen, initialMagnet, onAdd, onClose, onOpen, onBackgroundChange, initialSourceUrl, initialDescriptorUrl } = props;
  const [magnetInput, setMagnetInput] = useState('');
  const [category, setCategory] = useState(defaultFolder);
  const [inspectedFiles, setInspectedFiles] = useState<InspectFileItem[]>([]);
  const [isInspecting, setIsInspecting] = useState(false);
  const [inspectionSource, setInspectionSource] = useState<string>('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');
  const [showManifestEditor, setShowManifestEditor] = useState(false);
  const [customFileCount, setCustomFileCount] = useState<number>(16);
  const [pasteManifestText, setPasteManifestText] = useState('');
  const [inspectedHash, setInspectedHash] = useState('');
  const [inspectedTorrentName, setInspectedTorrentName] = useState('');
  const [backgroundMode, setBackgroundMode] = useState(false);
  const inspectTimeoutRef = useRef<any>(null);
  const [copiedMagnet, setCopiedMagnet] = useState(false);
  // Reset/initialize from the parent-provided source on every open or
  // whenever a different search result is selected. This prevents the prior
  // torrent's metadata from surviving into the next selection.
  useEffect(() => {
    if (!isOpen) return;

    const source = initialMagnet;
    setMagnetInput(source);
    setInspectedFiles([]);
    setInspectedHash('');
    setInspectedTorrentName('');
    setInspectionSource('');
    setCopiedMagnet(false);
    setBackgroundMode(false);
    setError('');
    setShowManifestEditor(false);
    setPasteManifestText('');
  }, [isOpen, initialMagnet]);
  const classifyFileType = (name: string): InspectFileItem['type'] => {
    const lower = String(name || '').toLowerCase();
    if (/\.(mp4|mkv|m4v|webm|mov|avi|wmv|flv|ts|m2ts)$/.test(lower)) return 'video';
    if (/\.(mp3|wav|flac|aac|ogg|m4a|opus|wma)$/.test(lower)) return 'audio';
    if (/\.(zip|rar|7z|tar|gz|bz2|xz|iso)$/.test(lower)) return 'archive';
    if (/\.(pdf|txt|md|json|csv|srt|vtt|ass|sub)$/.test(lower)) return 'document';
    return 'other';
  };
  const inferTorrentName = (
    files: { name: string; path?: string }[],
    fallback = ''
  ): string => {
    if (fallback.trim()) return fallback.trim();

    if (!files.length) return '';

    // Multi-file torrents commonly expose paths like:
    // "Torrent Folder Name/Season 1/Episode.mkv".
    // Use the common first path segment as the folder/torrent name.
    const segments = files
      .map(file => String(file.path || file.name || '').replace(/\\/g, '/').split('/').filter(Boolean))
      .filter(parts => parts.length > 1);

    if (segments.length === files.length) {
      const first = segments[0][0];
      if (first && segments.every(parts => parts[0] === first)) {
        return first;
      }
    }

    return String(files[0]?.name || '').replace(/\\/g, '/').split('/').filter(Boolean)[0] || '';
  };
  const applyFileList = (files: { index: number; name: string; size: number; path?: string; type?: string; priority?: number }[]) => {
    const singleFile = files.length === 1;
    setInspectedFiles(
      files.map((f) => ({
        index: Number(f.index),
        name: f.name,
        size: Number(f.size || 0),
        type: (f.type as InspectFileItem['type']) || classifyFileType(f.name),
        selected: singleFile ? true : Number(f.priority ?? 0) > 0
      }))
    );
    setCustomFileCount(files.length);
    setInspectedTorrentName(prev => prev || inferTorrentName(files));
  };
  const startSingleFileDownload = async (
    source: string,
    files: { index: number; name: string; size: number; path?: string; type?: string; priority?: number }[],
    hash?: string,
    seedrTaskId?: number | string | null,
    torrentName?: string
  ) => {
    if (files.length !== 1) return;

    const file = files[0];
    const fileSize = Number(file.size || 0);

    const manifest = [{
      index: Number(file.index),
      name: file.name,
      size: fileSize,
      priority: 1
    }];

    try {
      setIsLoading(true);
      setError('');

      // A single-file torrent needs no selection UI. Use Seedr whenever
      // the file fits in the currently available free-account space.
      // There is no hard 5 GB cutoff: remaining quota is the limit.
      let forceBackend: 'seedr' | 'qbittorrent' = 'qbittorrent';
      if (fileSize > 0) {
        try {
          const quota = await api.getSeedrQuota();
          if (quota.configured && fileSize <= quota.remainingSpace) {
            forceBackend = 'seedr';
          }
        } catch {
          // Quota lookup is best-effort; fall back to qBittorrent.
        }
      }

      const selectedBackend = seedrTaskId != null ? 'seedr' : forceBackend;
      let seedrSource =
        selectedBackend === 'seedr' && hash && /^[a-f0-9]{40}$/i.test(hash)
          ? `magnet:?xt=urn:btih:${hash.toLowerCase()}`
          : source;


      await onAdd(
        seedrSource,
        category,
        [Number(file.index)],
        manifest,
        hash || undefined,
        selectedBackend,
        undefined,
        seedrTaskId ?? undefined,
        torrentName || inspectedTorrentName || file.name
      );
      setBackgroundMode(false);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to start cloud torrent download');
    } finally {
      setIsLoading(false);
    }
  };
  // Resolve torrent metadata without starting a Seedr transfer.
  const triggerInspect = async (link: string, background = false) => {
    const source = link.trim();
    if (!source) {
      setInspectedFiles([]);
      setInspectionSource('');
      return;
    }

    try {
      setIsInspecting(true);
      setBackgroundMode(background);
      setError('');
      if (background) {
        onBackgroundChange?.({
          active: true,
          title: 'Resolving torrent metadata',
          message: 'Working in the background. Seedr has not been started.'
        });
      }
      setInspectedFiles([]);

      // Metadata inspection must never add the magnet to Seedr. The backend
      // resolves only the torrent metadata so the user can choose files first.
      setInspectionSource(
        isSearchGrab
          ? 'Loading torrent metadata...'
          : 'Resolving torrent metadata without starting Seedr...'
      );

      const data = await api.inspectMagnet(source, category, initialSourceUrl, initialDescriptorUrl);

      if (data?.pending) {
      const pendingHash = String(data.hash || '').trim().toLowerCase();
      if (pendingHash) setInspectedHash(pendingHash);
      setInspectionSource(data.message || 'Torrent metadata is still resolving in the background...');
      if (background) {
        onBackgroundChange?.({
          active: true,
          title: 'Resolving torrent metadata',
          message: data.message || 'Still resolving in the background. Seedr has not been started.',
          jobId: String((data as any).jobId || pendingHash || '')
        });
      }
      return;
    }

    if (data && Array.isArray(data.files) && data.files.length > 0) {
        const hash = String(data.hash || '').trim().toLowerCase();
        setInspectedHash(hash);
         const resolvedSource =
           data.source === 'search_torrent_descriptor' && hash
             ? `magnet:?xt=urn:btih:${hash}&dn=${encodeURIComponent(data.name || data.files[0]?.name || 'torrent')}`
             : source;

         if (resolvedSource !== source) {
           setMagnetInput(resolvedSource);
         }
        applyFileList(data.files);
        setInspectedTorrentName(String(data.name || '').trim());

        if (data.files.length === 1) {

          await startSingleFileDownload(
            resolvedSource,
            data.files,
            hash,
            null,
            inferTorrentName(data.files, String(data.name || '').trim())
          );
          return;
        }

         setInspectionSource(isSearchGrab ? '✓ Torrent metadata loaded • Multi-file torrent is not started while you choose files' : '✓ Torrent metadata loaded • Seedr is not started yet');
        if (background) {
          onBackgroundChange?.({
            active: false,
            title: 'Torrent metadata ready',
            message: `${data.files.length} file${data.files.length === 1 ? '' : 's'} found. Open the selector when ready.`,
            ready: true
          });
        }
        return;
      }

      const hash = String(data?.hash || '').trim().toLowerCase();
      if (!hash) {
        throw new Error(
          data?.message ||
          'Torrent metadata did not return a hash. Please verify the magnet URI and try again.'
        );
      }

      if (!data?.pending && data?.source !== 'qbt_torrent_pending') {
        throw new Error(data?.message || 'Torrent metadata did not return the file list.');
      }

      const maxAttempts = 120;
      for (let attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
          const files = await api.getTorrentFiles(hash);
          if (files.length > 0) {
            const normalizedFiles = files.map((f) => ({
              index: f.index,
              name: f.name,
              size: f.size,
              path: f.path,
              type: classifyFileType(f.name),
              priority: f.priority
            }));
            setInspectedHash(hash);
            setInspectedTorrentName(prev => prev || inferTorrentName(normalizedFiles));
            applyFileList(normalizedFiles);

            if (normalizedFiles.length === 1) {

              await startSingleFileDownload(
                source,
                normalizedFiles,
                hash,
                null,
                inferTorrentName(normalizedFiles, inspectedTorrentName)
              );
              return;
            }

            setInspectionSource('✓ Torrent metadata loaded • Seedr is not started yet');
            if (background) {
              onBackgroundChange?.({
                active: false,
                title: 'Torrent metadata ready',
                message: `${normalizedFiles.length} file${normalizedFiles.length === 1 ? '' : 's'} found. Open the selector when ready.`,
                ready: true
              });
            }
            return;
          }
        } catch {
          // Metadata may not be available yet; keep polling.
        }

        const seconds = attempt * 2;
        setInspectionSource(
          `Resolving torrent metadata... (${seconds}s) • Seedr has not been started`
        );
        await new Promise(resolve => setTimeout(resolve, 2000));
      }

      throw new Error(
        'Torrent metadata could not be resolved yet. Click Load File List to retry.'
      );
    } catch (err: any) {
      console.warn('Inspect magnet error:', err);
      setInspectedFiles([]);
      setInspectionSource('');
      const message = err?.message || 'Could not load torrent metadata.';
      setError(message);
      if (background) {
        onBackgroundChange?.({
          active: false,
          title: 'Torrent metadata failed',
          message,
          error: message
        });
      }
    } finally {
      setIsInspecting(false);
    }
  };
  const handleInputChange = (val: string) => {
    setBackgroundMode(false);
    setMagnetInput(val);
    setError('');
    setInspectedFiles([]);
    setInspectedHash('');
    setInspectedTorrentName('');
    setInspectionSource('');
    if (inspectTimeoutRef.current) clearTimeout(inspectTimeoutRef.current);
  };
  const toggleFile = (index: number) => {
    setInspectedFiles(prev =>
      prev.map(f => (f.index === index ? { ...f, selected: !f.selected } : f))
    );
  };
  const selectAll = (selected: boolean) => {
    setInspectedFiles(prev => prev.map(f => ({ ...f, selected })));
  };
  const selectOnlyVideos = () => {
    setInspectedFiles(prev =>
      prev.map(f => ({ ...f, selected: f.type === 'video' }))
    );
  };
  const selectOnlyAudio = () => {
    setInspectedFiles(prev =>
      prev.map(f => ({ ...f, selected: f.type === 'audio' }))
    );
  };
  const selectedFiles = inspectedFiles.filter(f => f.selected);
  const selectedCount = selectedFiles.length;
  const totalSelectedSize = selectedFiles.reduce((acc, f) => acc + f.size, 0);
  const totalTorrentSize = inspectedFiles.reduce((acc, f) => acc + f.size, 0);
  const isSingleFile = inspectedFiles.length === 1;
  const isSearchGrab = /^\/api\/search\/torrents\/grab\//i.test(magnetInput.trim());
  const isDirectSeedrSource =
    !isSearchGrab &&
    (/^magnet:\?/i.test(magnetInput.trim()) || /^[a-f0-9]{40}$/i.test(magnetInput.trim()));
  const resolveMagnetUri = async (): Promise<string> => {
    const source = magnetInput.trim();

    if (/^magnet:\?/i.test(source)) return source;
    if (/^[a-f0-9]{40}$/i.test(source)) {
      const name = inspectedFiles[0]?.name?.split('/').pop() || 'torrent';
      return `magnet:?xt=urn:btih:${source.toLowerCase()}&dn=${encodeURIComponent(name)}`;
    }

    if (source.startsWith('/api/') || /^https?:\/\//i.test(source)) {
      const response = await fetch(source);
      const text = (await response.text()).trim();
      if (/^magnet:\?/i.test(text)) return text;
    }

    if (inspectedHash) {
      const name = inspectedFiles[0]?.name?.split('/').pop() || 'torrent';
      return `magnet:?xt=urn:btih:${inspectedHash}&dn=${encodeURIComponent(name)}`;
    }

    throw new Error('A magnet link is not available for this torrent.');
  };
  const handleCopyMagnet = async () => {
    try {
      const magnet = await resolveMagnetUri();

      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(magnet);
      } else {
        const area = document.createElement('textarea');
        area.value = magnet;
        area.style.position = 'fixed';
        area.style.opacity = '0';
        document.body.appendChild(area);
        area.focus();
        area.select();
        document.execCommand('copy');
        area.remove();
      }

      setCopiedMagnet(true);
      window.setTimeout(() => setCopiedMagnet(false), 1600);
    } catch (err: any) {
      setError(err?.message || 'Could not copy the magnet link.');
    }
  };
  const handleDownloadTorrent = async () => {
    if (!inspectedHash) {
      setError('The torrent hash is not available yet.');
      return;
    }

    try {
      const blob = await api.exportTorrent(inspectedHash);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      const baseName = inspectedFiles[0]?.name?.split('/').pop() || 'torrent';
      anchor.href = url;
      anchor.download = baseName.replace(/\.[^.]+$/, '') + '.torrent';
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err?.message || 'Could not download the .torrent file.');
    }
  };
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    const magnet = magnetInput;
    if (!/^magnet:\?/i.test(magnet.trim())) {
      setError('Please provide a magnet link.');
      return;
    }

    try {
      setIsLoading(true);
      setError('');

      // Direct Seedr path: send only the magnet link. No metadata lookup,
      // quota lookup, file manifest, file selection, or Seedr selection API.
      await onAdd(
        magnet,
        category,
        undefined,
        undefined,
        undefined,
        'seedr'
      );

      setBackgroundMode(false);
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to send the magnet to Seedr');
    } finally {
      setIsLoading(false);
    }
  };
;

  return {
    isOpen,
    onClose,
    onOpen,
    onAdd,
    defaultFolder,
    magnetInput,
    setMagnetInput,
    inspectedFiles,
    setInspectedFiles,
    isInspecting,
    inspectionSource,
    setInspectionSource,
    isLoading,
    error,
    setError,
    inspectedHash,
    setInspectedHash,
    setInspectedTorrentName,
    backgroundMode,
    setBackgroundMode,
    copiedMagnet,
    handleInputChange,
    toggleFile,
    selectAll,
    selectOnlyVideos,
    selectOnlyAudio,
    selectedCount,
    totalSelectedSize,
    totalTorrentSize,
    isSingleFile,
    isSearchGrab,
    handleCopyMagnet,
    handleDownloadTorrent,
    handleSubmit,
  };
}

export type PanelModel = ReturnType<typeof useAddMagnetModel>;
