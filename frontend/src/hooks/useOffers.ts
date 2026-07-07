import { useCallback, useEffect, useRef, useState } from 'react';

import {
  fetchOffers,
  type OfferListFilters,
  type OfferListPage,
  type OfferSummary,
} from '../api/offers';

export interface UseOffersResult {
  offers: OfferSummary[];
  total: number;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

// Filter changes (esp. every keystroke in "Min salary") are debounced by this
// much before firing the network fetch (BUG17) — the initial load on mount
// is exempt so the page doesn't sit idle for no reason.
const FILTER_DEBOUNCE_MS = 300;

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to load offers';
}

export function useOffers(filters: OfferListFilters, page: OfferListPage): UseOffersResult {
  const [offers, setOffers] = useState<OfferSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const isFirstRun = useRef(true);

  const { source, remote, seniority, minSalary, minGrade } = filters;
  const { limit, offset } = page;

  // react-hooks/set-state-in-effect forbids an effect calling a hoisted
  // (e.g. useCallback) function that sets state, so the automatic
  // fetch-on-filter-change below is a self-contained inline effect body,
  // duplicating refetch's logic rather than delegating to it.
  useEffect(() => {
    let ignore = false;

    async function run() {
      setLoading(true);
      try {
        const result = await fetchOffers(
          { source, remote, seniority, minSalary, minGrade },
          { limit, offset },
        );
        if (!ignore) {
          setOffers(result.items);
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

    if (isFirstRun.current) {
      isFirstRun.current = false;
      run();
      return () => {
        ignore = true;
      };
    }

    const timer = setTimeout(run, FILTER_DEBOUNCE_MS);
    return () => {
      ignore = true;
      clearTimeout(timer);
    };
  }, [source, remote, seniority, minSalary, minGrade, limit, offset]);

  const refetch = useCallback(() => {
    setLoading(true);
    fetchOffers({ source, remote, seniority, minSalary, minGrade }, { limit, offset })
      .then((result) => {
        setOffers(result.items);
        setTotal(result.total);
        setError(null);
      })
      .catch((err: unknown) => {
        setError(errorMessage(err));
      })
      .finally(() => {
        setLoading(false);
      });
  }, [source, remote, seniority, minSalary, minGrade, limit, offset]);

  return { offers, total, loading, error, refetch };
}
