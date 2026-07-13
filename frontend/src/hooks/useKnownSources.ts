import { useEffect, useState } from 'react';

import { fetchConnectors, type ConnectorOption } from '../api/connectors';

export interface UseKnownSourcesResult {
  sources: ConnectorOption[];
}

export function useKnownSources(): UseKnownSourcesResult {
  const [sources, setSources] = useState<ConnectorOption[]>([]);

  useEffect(() => {
    fetchConnectors()
      .then(setSources)
      .catch(() => {
        // best-effort; callers already render fine with an empty list while this resolves
      });
  }, []);

  return { sources };
}
