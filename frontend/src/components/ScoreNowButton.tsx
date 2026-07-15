import { useState } from 'react';

import { triggerBatchScoring, type ScoringStatus } from '../api/scoring';

interface ScoreNowButtonProps {
  status: ScoringStatus | null;
  onScored: () => void;
}

function ZapIcon() {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden="true"
      className="shrink-0"
    >
      <path d="M13 2 3 14h7l-1 8 10-12h-7z" />
    </svg>
  );
}

function defaultSubtitle(status: ScoringStatus | null): string {
  if (status === null) {
    return 'Score unscored offers now';
  }
  const scored = status.total_offers - status.unscored_backlog;
  return `${scored} / ${status.total_offers}`;
}

export function ScoreNowButton({ status, onScored }: ScoreNowButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  const running = status?.running ?? false;
  const disabled = loading || running;

  const handleClick = async () => {
    if (disabled) return;

    setLoading(true);
    setError(null);
    setSummary(null);
    try {
      const result = await triggerBatchScoring();
      setSummary(`Scored ${result.scored}, ${result.failed} failed, ${result.remaining} remaining`);
      onScored();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to trigger scoring');
    } finally {
      setLoading(false);
    }
  };

  const subtitle = disabled ? 'Scoring…' : (error ?? summary ?? defaultSubtitle(status));

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={disabled}
      className="card card-interactive card-accent flex min-w-0 flex-1 flex-col items-start gap-0.5 px-3 py-3 text-left"
    >
      <span className="flex w-full items-center gap-1.5 truncate text-xs font-medium text-[var(--color-accent)]">
        <ZapIcon />
        <span className="truncate">Score now</span>
      </span>
      <span
        className={
          error
            ? 'w-full truncate text-[10px] text-[var(--color-danger)]'
            : 'w-full truncate text-[10px] text-[var(--color-text-muted)] opacity-70'
        }
      >
        {subtitle}
      </span>
    </button>
  );
}
