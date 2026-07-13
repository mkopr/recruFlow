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
  saveRange: (connector: string, range: FetchRangeUpdateRequest) => Promise<boolean>;
  saveRangeAll: (range: FetchRangeUpdateRequest) => Promise<boolean>;
  saveAutoFetch: (connector: string, enabled: boolean) => Promise<void>;
  saveAutoFetchAll: (enabled: boolean) => Promise<void>;
  refetch: () => Promise<void>;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to update fetch range settings';
}

export function useFetchRangeSettings(): UseFetchRangeSettingsResult {
  const { sources, refetch } = useSchedulerStatus();
  const [savingByConnector, setSavingByConnector] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  async function saveRange(connector: string, range: FetchRangeUpdateRequest): Promise<boolean> {
    setSavingByConnector((prev) => ({ ...prev, [connector]: true }));
    setError(null);
    let success = false;
    try {
      await updateSourceFetchRange(connector, range);
      await refetch();
      success = true;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => ({ ...prev, [connector]: false }));
    }
    return success;
  }

  async function saveRangeAll(range: FetchRangeUpdateRequest): Promise<boolean> {
    setSavingByConnector((prev) => {
      const next = { ...prev };
      for (const source of sources) next[source.connector] = true;
      return next;
    });
    setError(null);
    let success = false;
    try {
      await updateAllSourceFetchRanges(range);
      await refetch();
      success = true;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingByConnector((prev) => {
        const next = { ...prev };
        for (const source of sources) next[source.connector] = false;
        return next;
      });
    }
    return success;
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
