import { useState } from 'react';

import { updateAllSourceIntervals, updateSourceInterval } from '../api/scheduler';
import { useSchedulerStatus, type UseSchedulerStatusResult } from './useSchedulerStatus';

export interface UseFetchCadenceResult {
  sources: UseSchedulerStatusResult['sources'];
  saving: Record<string, boolean>;
  error: string | null;
  saveOne: (connector: string, seconds: number) => Promise<void>;
  saveAll: (seconds: number) => Promise<void>;
  refetch: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to update fetch interval';
}

export function useFetchCadence(): UseFetchCadenceResult {
  const { sources, refetch } = useSchedulerStatus();
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  async function saveOne(connector: string, seconds: number): Promise<void> {
    setSaving((prev) => ({ ...prev, [connector]: true }));
    setError(null);
    try {
      await updateSourceInterval(connector, seconds);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving((prev) => ({ ...prev, [connector]: false }));
    }
  }

  async function saveAll(seconds: number): Promise<void> {
    setSaving((prev) => {
      const next = { ...prev };
      for (const source of sources) next[source.connector] = true;
      return next;
    });
    setError(null);
    try {
      await updateAllSourceIntervals(seconds);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving((prev) => {
        const next = { ...prev };
        for (const source of sources) next[source.connector] = false;
        return next;
      });
    }
  }

  return { sources, saving, error, saveOne, saveAll, refetch };
}
