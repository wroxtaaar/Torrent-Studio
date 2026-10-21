import { useState, useEffect, useCallback } from 'react';
import { api } from '../../api/client.ts';

export function useBackgroundMetadataJobs() {
  type BackgroundMetadataJobRecord = {
    jobId: string;
    hash: string;
    name: string;
    status: string;
    rounds: number;
    startedAt: number;
    updatedAt: number;
    deadlineAt: number;
    elapsedSeconds: number;
    remainingSeconds: number;
    fileCount: number;
    totalSize: number;
    source: string;
    error?: string | null;
  };
  const [backgroundMetadataJob, setBackgroundMetadataJob] = useState<{
    active: boolean;
    title: string;
    message: string;
    ready?: boolean;
    error?: string;
    jobId?: string;
    hash?: string;
  } | null>(null);
  const [backgroundMetadataJobs, setBackgroundMetadataJobs] = useState<BackgroundMetadataJobRecord[]>([]);
  const [backgroundMetadataLoading, setBackgroundMetadataLoading] = useState(false);
  // Keep background metadata jobs connected to the UI after the selector closes.
  // Once a resolver finishes, the cached metadata is immediately available when
  // the user opens the selector again.
  useEffect(() => {
    const jobId = backgroundMetadataJob?.jobId;
    if (!backgroundMetadataJob?.active || !jobId) return;

    let stopped = false;
    const poll = async () => {
      try {
        const data = await api.getTorrentMetadataStatus(jobId);
        if (stopped) return;

        if (Array.isArray(data?.files) && data.files.length > 0) {
          setBackgroundMetadataJob({
            active: false,
            ready: true,
            title: 'Torrent metadata ready',
            message: `${data.files.length} file${data.files.length === 1 ? '' : 's'} found. Open the selector to choose files.`,
            jobId
          });
          return;
        }

        if (data?.status === 'error') {
          setBackgroundMetadataJob({
            active: false,
            error: String(data?.message || 'Torrent metadata could not be resolved.'),
            title: 'Torrent metadata failed',
            message: String(data?.message || 'Torrent metadata could not be resolved.'),
            jobId
          });
        }
      } catch {
        // The job may still be running or the Render instance may be waking.
        // Keep polling rather than turning a transient status request into a
        // false failure.
      }
    };

    void poll();
    const timer = window.setInterval(() => { void poll(); }, 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [backgroundMetadataJob?.active, backgroundMetadataJob?.jobId]);
  const refreshBackgroundMetadataJobs = useCallback(async () => {
    try {
      setBackgroundMetadataLoading(true);
      const data = await api.getTorrentMetadataJobs();
      setBackgroundMetadataJobs(Array.isArray(data?.jobs) ? data.jobs : []);
    } catch {
      // Metadata jobs are best-effort UI state. A transient API/Render wake-up
      // failure must not affect the rest of the Files screen.
    } finally {
      setBackgroundMetadataLoading(false);
    }
  }, []);
  // Restore the server-side metadata queue when the page loads. Keep polling
  // while at least one job is still resolving, then slow down once everything
  // is terminal so the list remains useful without unnecessary requests.
  const hasActiveBackgroundMetadataJobs = backgroundMetadataJobs.some(
    job => job.status === 'queued' || job.status === 'resolving'
  );
  useEffect(() => {
    void refreshBackgroundMetadataJobs();
    if (!hasActiveBackgroundMetadataJobs) return;
    const timer = window.setInterval(
      () => { void refreshBackgroundMetadataJobs(); },
      5000
    );
    return () => window.clearInterval(timer);
  }, [refreshBackgroundMetadataJobs, hasActiveBackgroundMetadataJobs]);

  return {
    backgroundMetadataJob,
    setBackgroundMetadataJob,
  };
}
