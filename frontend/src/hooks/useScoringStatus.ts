import { useEffect, useRef, useState } from 'react';

import { fetchScoringStatus, type ScoringStatus } from '../api/scoring';

const POLL_WHILE_RUNNING_MS = 1500;
const POLL_WHILE_IDLE_MS = 5000;

export interface UseScoringStatusResult {
  status: ScoringStatus | null;
}

export function useScoringStatus(): UseScoringStatusResult {
  const [status, setStatus] = useState<ScoringStatus | null>(null);
  // Read inside the poll loop below without re-subscribing the effect on every
  // update — the loop's own next-delay decision needs the latest value, not
  // the one captured when the effect ran.
  const runningRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;

    async function poll() {
      try {
        const result = await fetchScoringStatus();
        if (!cancelled) {
          runningRef.current = result.running;
          setStatus(result);
        }
      } catch {
        // best-effort progress display; the offer list and fetch button already
        // surface their own errors, so a failed status poll is silent here
      }
      if (!cancelled) {
        timeoutId = setTimeout(
          poll,
          runningRef.current ? POLL_WHILE_RUNNING_MS : POLL_WHILE_IDLE_MS,
        );
      }
    }

    poll();

    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  }, []);

  return { status };
}
