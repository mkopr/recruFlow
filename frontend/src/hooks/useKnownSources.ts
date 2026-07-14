import { useCallback, useEffect, useState } from 'react';

import { fetchConnectors, type ConnectorOption } from '../api/connectors';

export interface UseKnownSourcesResult {
  sources: ConnectorOption[];
  refetch: () => void;
}

export function useKnownSources(): UseKnownSourcesResult {
  const [sources, setSources] = useState<ConnectorOption[]>([]);

  const refetch = useCallback(() => {
    fetchConnectors()
      .then(setSources)
      .catch(() => {
        // best-effort; callers already render fine with an empty list while this resolves
      });
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { sources, refetch };
}
