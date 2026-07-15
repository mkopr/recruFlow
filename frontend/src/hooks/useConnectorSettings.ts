import { useState } from 'react';

import {
  type FetchRangeUpdateRequest,
  updateAllSourceAutoFetch,
  updateAllSourceEnabled,
  updateAllSourceFetchRanges,
  updateAllSourceIntervals,
  updateSourceAutoFetch,
  updateSourceEnabled,
  updateSourceFetchRange,
  updateSourceFetchScope,
  updateSourceInterval,
} from '../api/scheduler';
import { useSchedulerStatus, type UseSchedulerStatusResult } from './useSchedulerStatus';

export interface UseConnectorSettingsResult {
  sources: UseSchedulerStatusResult['sources'];
  savingByConnector: Record<string, boolean>;
  error: string | null;
  saveInterval: (connector: string, seconds: number) => Promise<void>;
  saveIntervalAll: (seconds: number) => Promise<void>;
  saveRange: (connector: string, range: FetchRangeUpdateRequest) => Promise<boolean>;
  saveRangeAll: (range: FetchRangeUpdateRequest) => Promise<boolean>;
  saveFetchScope: (connector: string, mode: 'all' | 'filtered') => Promise<boolean>;
  saveAutoFetch: (connector: string, enabled: boolean) => Promise<void>;
  saveAutoFetchAll: (enabled: boolean) => Promise<void>;
  saveEnabled: (connector: string, enabled: boolean) => Promise<void>;
  saveEnabledAll: (enabled: boolean) => Promise<void>;
  refetch: () => Promise<void>;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to update connector settings';
}

export function useConnectorSettings(): UseConnectorSettingsResult {
  const { sources, refetch } = useSchedulerStatus();
  const [savingByConnector, setSavingByConnector] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  function setSavingOne(connector: string, value: boolean): void {
    setSavingByConnector((prev) => ({ ...prev, [connector]: value }));
  }

  function setSavingAll(value: boolean): void {
    setSavingByConnector((prev) => {
      const next = { ...prev };
      for (const source of sources) next[source.connector] = value;
      return next;
    });
  }

  async function saveInterval(connector: string, seconds: number): Promise<void> {
    setSavingOne(connector, true);
    setError(null);
    try {
      await updateSourceInterval(connector, seconds);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingOne(connector, false);
    }
  }

  async function saveIntervalAll(seconds: number): Promise<void> {
    setSavingAll(true);
    setError(null);
    try {
      await updateAllSourceIntervals(seconds);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingAll(false);
    }
  }

  async function saveRange(connector: string, range: FetchRangeUpdateRequest): Promise<boolean> {
    setSavingOne(connector, true);
    setError(null);
    let success = false;
    try {
      await updateSourceFetchRange(connector, range);
      await refetch();
      success = true;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingOne(connector, false);
    }
    return success;
  }

  async function saveRangeAll(range: FetchRangeUpdateRequest): Promise<boolean> {
    setSavingAll(true);
    setError(null);
    let success = false;
    try {
      await updateAllSourceFetchRanges(range);
      await refetch();
      success = true;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingAll(false);
    }
    return success;
  }

  async function saveFetchScope(connector: string, mode: 'all' | 'filtered'): Promise<boolean> {
    setSavingOne(connector, true);
    setError(null);
    let success = false;
    try {
      await updateSourceFetchScope(connector, { mode });
      await refetch();
      success = true;
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingOne(connector, false);
    }
    return success;
  }

  async function saveAutoFetch(connector: string, enabled: boolean): Promise<void> {
    setSavingOne(connector, true);
    setError(null);
    try {
      await updateSourceAutoFetch(connector, enabled);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingOne(connector, false);
    }
  }

  async function saveAutoFetchAll(enabled: boolean): Promise<void> {
    setSavingAll(true);
    setError(null);
    try {
      await updateAllSourceAutoFetch(enabled);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingAll(false);
    }
  }

  async function saveEnabled(connector: string, enabled: boolean): Promise<void> {
    setSavingOne(connector, true);
    setError(null);
    try {
      await updateSourceEnabled(connector, enabled);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingOne(connector, false);
    }
  }

  async function saveEnabledAll(enabled: boolean): Promise<void> {
    setSavingAll(true);
    setError(null);
    try {
      await updateAllSourceEnabled(enabled);
      await refetch();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSavingAll(false);
    }
  }

  return {
    sources,
    savingByConnector,
    error,
    saveInterval,
    saveIntervalAll,
    saveRange,
    saveRangeAll,
    saveFetchScope,
    saveAutoFetch,
    saveAutoFetchAll,
    saveEnabled,
    saveEnabledAll,
    refetch,
  };
}
