import { useCallback, useEffect, useState } from 'react';

import { fetchSchedulerStatus, type SourceStatus } from '../api/scheduler';

export interface UseSchedulerStatusResult {
  sources: SourceStatus[];
  refetch: () => Promise<void>;
}

export function useSchedulerStatus(): UseSchedulerStatusResult {
  const [sources, setSources] = useState<SourceStatus[]>([]);

  const refetch = useCallback(() => {
    return fetchSchedulerStatus()
      .then(setSources)
      .catch(() => {
        // best-effort staleness display; the offers list is the primary content
        // and already surfaces its own errors, so a failed status fetch is silent here
      });
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { sources, refetch };
}
