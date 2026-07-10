import { useState } from 'react';

import {
  type FetchRangeUpdateRequest,
  updateAllSourceAutoFetch,
  updateAllSourceFetchRanges,
  updateSourceAutoFetch,
  updateSourceFetchRange,
} from '../api/scheduler';
import { useSchedulerStatus, type UseSchedulerStatusResult } from './useSchedulerStatus';

export interface UseFetchRangeSettingsResult {
  sources: UseSchedulerStatusResult['sources'];
  savingByConnector: Record<string, boolean>;
  error: string | null;
  saveRange: (connector: string, range: FetchRangeUpdateRequest) => Promise<void>;
  saveRangeAll: (range: FetchRangeUpdateRequest) => Promise<void>;
  saveAutoFetch: (connector: string, enabled: boolean) => Promise<void>;
  saveAutoFetchAll: (enabled: boolean) => Promise<void>;
  refetch: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to update fetch range settings';
}

export function useFetchRangeSettings(): UseFetchRangeSettingsResult {
  const { sources, refetch } = useSchedulerStatus();
  const [savingByConnector, setSavingByConnector] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  async function saveRange(connector: string, range: FetchRangeUpdateRequest): Promise<void> {
    setSavingByConnector((prev) => ({ ...prev, [connector]: true }));
    setError(null);
    try {
      await updateSourceFetchRange(connector, range);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => ({ ...prev, [connector]: false }));
    }
  }

  async function saveRangeAll(range: FetchRangeUpdateRequest): Promise<void> {
    setSavingByConnector((prev) => {
      const next = { ...prev };
      for (const source of sources) next[source.connector] = true;
      return next;
    });
    setError(null);
    try {
      await updateAllSourceFetchRanges(range);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => {
        const next = { ...prev };
        for (const source of sources) next[source.connector] = false;
        return next;
      });
    }
  }

  async function saveAutoFetch(connector: string, enabled: boolean): Promise<void> {
    setSavingByConnector((prev) => ({ ...prev, [connector]: true }));
    setError(null);
    try {
      await updateSourceAutoFetch(connector, enabled);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => ({ ...prev, [connector]: false }));
    }
  }

  async function saveAutoFetchAll(enabled: boolean): Promise<void> {
    setSavingByConnector((prev) => {
      const next = { ...prev };
      for (const source of sources) next[source.connector] = true;
      return next;
    });
    setError(null);
    try {
      await updateAllSourceAutoFetch(enabled);
      refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => {
        const next = { ...prev };
        for (const source of sources) next[source.connector] = false;
        return next;
      });
    }
  }

  return {
    sources,
    savingByConnector,
    error,
    saveRange,
    saveRangeAll,
    saveAutoFetch,
    saveAutoFetchAll,
    refetch,
  };
}
