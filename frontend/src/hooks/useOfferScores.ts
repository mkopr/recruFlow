import { useCallback, useEffect, useRef, useState } from 'react';

import { fetchOfferScore, type MatchScoreResponse } from '../api/offerScore';

export interface UseOfferScoresResult {
  scores: Record<number, MatchScoreResponse | null>;
  loading: boolean;
  refetch: () => void;
}

export function useOfferScores(offerIds: number[]): UseOfferScoresResult {
  const [scores, setScores] = useState<Record<number, MatchScoreResponse | null>>({});
  const [loading, setLoading] = useState(offerIds.length > 0);
  const scoresRef = useRef(scores);
  useEffect(() => {
    scoresRef.current = scores;
  }, [scores]);

  const key = offerIds.join(',');

  // react-hooks/set-state-in-effect forbids an effect calling a hoisted
  // (e.g. useCallback) function that sets state, so this is a self-contained
  // inline effect body, mirroring useOffers.ts's own convention.
  useEffect(() => {
    let ignore = false;

    async function run() {
      if (offerIds.length === 0) {
        setLoading(false);
        return;
      }

      // Only pull ids not already cached (BUG17) — the offers array gets a new
      // reference on every fetch, but that shouldn't re-request a score this
      // hook already has for an id it's seen before.
      const idsToFetch = offerIds.filter((id) => !(id in scoresRef.current));
      if (idsToFetch.length === 0) {
        setLoading(false);
        return;
      }

      setLoading(true);
      const results = await Promise.allSettled(idsToFetch.map((id) => fetchOfferScore(id)));

      if (!ignore) {
        setScores((prev) => {
          const next = { ...prev };
          idsToFetch.forEach((id, index) => {
            const result = results[index];
            next[id] = result.status === 'fulfilled' ? result.value : null;
          });
          return next;
        });
        setLoading(false);
      }
    }

    run();

    return () => {
      ignore = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // Lets a caller re-pull scores for the *same* offer-id list once background
  // scoring completes (BUG16) — the effect above only re-fetches when that
  // list itself changes, which never happens just because a score arrived.
  const refetch = useCallback(() => {
    if (offerIds.length === 0) {
      setScores({});
      setLoading(false);
      return;
    }

    setLoading(true);
    Promise.allSettled(offerIds.map((id) => fetchOfferScore(id))).then((results) => {
      const next: Record<number, MatchScoreResponse | null> = {};
      offerIds.forEach((id, index) => {
        const result = results[index];
        next[id] = result.status === 'fulfilled' ? result.value : null;
      });
      setScores(next);
      setLoading(false);
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return { scores, loading, refetch };
}
