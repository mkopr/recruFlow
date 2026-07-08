import { useCallback, useEffect, useState } from 'react';

import {
  fetchFailures,
  type Failure,
  type FailureListFilters,
  type FailureListPage,
  type FailureProcess,
} from '../api/failures';

export interface UseFailuresResult {
  failures: Failure[];
  total: number;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to load failures';
}

export function useFailures(
  process: FailureProcess,
  filters: FailureListFilters,
  page: FailureListPage,
): UseFailuresResult {
  const [failures, setFailures] = useState<Failure[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const { failureType, source, offerId, profileId, status } = filters;
  const { limit, offset } = page;

  // react-hooks/set-state-in-effect forbids an effect calling a hoisted (e.g. useCallback)
  // function that sets state, so the automatic fetch-on-filter-change below is a
  // self-contained inline effect body, duplicating refetch's logic rather than delegating
  // to it (mirrors useOffers.ts's own effect).
  useEffect(() => {
    let ignore = false;

    async function run() {
      setLoading(true);
      try {
        const result = await fetchFailures(
          process,
          { failureType, source, offerId, profileId, status },
          { limit, offset },
        );
        if (!ignore) {
          setFailures(result.items);
          setTotal(result.total);
          setError(null);
        }
      } catch (err) {
        if (!ignore) {
          setError(errorMessage(err));
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    run();
    return () => {
      ignore = true;
    };
  }, [process, failureType, source, offerId, profileId, status, limit, offset]);

  const refetch = useCallback(() => {
    setLoading(true);
    fetchFailures(process, { failureType, source, offerId, profileId, status }, { limit, offset })
      .then((result) => {
        setFailures(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(errorMessage(err));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [process, failureType, source, offerId, profileId, status, limit, offset]);

  return { failures, total, loading, error, refetch };
}
