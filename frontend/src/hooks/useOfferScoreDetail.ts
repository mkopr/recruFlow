import { useEffect, useState } from 'react';

import { fetchOfferScore, type MatchScoreResponse } from '../api/offerScore';

export interface UseOfferScoreDetailResult {
  score: MatchScoreResponse | null;
  loading: boolean;
}

// Fetches the full score breakdown (rationale, dimensions) for a single offer,
// on demand — used when a user opens the score drawer, not on every row of the
// offer list (BUG26: bulk per-row fetching is what made the list page fire one
// HTTP request per offer). The list itself already carries each offer's grade
// inline via GET /offers, so this hook is only needed for the drawer's detail.
export function useOfferScoreDetail(offerId: number | null): UseOfferScoreDetailResult {
  const [score, setScore] = useState<MatchScoreResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // react-hooks/set-state-in-effect forbids an effect calling setState directly
  // in its body, so the null-offerId reset also runs inside this self-contained
  // async function rather than at the top of the effect (mirrors useOffers.ts).
  useEffect(() => {
    let ignore = false;

    async function run() {
      if (offerId == null) {
        setScore(null);
        setLoading(false);
        return;
      }

      setScore(null);
      setLoading(true);
      try {
        const result = await fetchOfferScore(offerId);
        if (!ignore) {
          setScore(result);
        }
      } catch {
        if (!ignore) {
          setScore(null);
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
  }, [offerId]);

  return { score, loading };
}
