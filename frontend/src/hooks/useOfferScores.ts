import { useEffect, useState } from 'react';

import { fetchOfferScore, type MatchScoreResponse } from '../api/offerScore';

export interface UseOfferScoresResult {
  scores: Record<number, MatchScoreResponse | null>;
  loading: boolean;
}

export function useOfferScores(offerIds: number[]): UseOfferScoresResult {
  const [scores, setScores] = useState<Record<number, MatchScoreResponse | null>>({});
  const [loading, setLoading] = useState(offerIds.length > 0);

  const key = offerIds.join(',');

  // react-hooks/set-state-in-effect forbids an effect calling a hoisted
  // (e.g. useCallback) function that sets state, so this is a self-contained
  // inline effect body, mirroring useOffers.ts's own convention.
  useEffect(() => {
    let ignore = false;

    async function run() {
      if (offerIds.length === 0) {
        setScores({});
        setLoading(false);
        return;
      }

      setLoading(true);
      const results = await Promise.allSettled(offerIds.map((id) => fetchOfferScore(id)));

      if (!ignore) {
        const next: Record<number, MatchScoreResponse | null> = {};
        offerIds.forEach((id, index) => {
          const result = results[index];
          next[id] = result.status === 'fulfilled' ? result.value : null;
        });
        setScores(next);
        setLoading(false);
      }
    }

    run();

    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { scores, loading };
}
