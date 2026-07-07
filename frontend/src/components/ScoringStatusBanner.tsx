import type { ScoringStatus } from '../api/scoring';

interface ScoringStatusBannerProps {
  status: ScoringStatus | null;
}

export function ScoringStatusBanner({ status }: ScoringStatusBannerProps) {
  if (status === null || (!status.running && status.finished_at === null)) {
    return null;
  }

  if (status.running) {
    const pct = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
    return (
      <div className="card flex flex-col gap-2 px-4 py-3 text-sm" role="status">
        <span>
          Scoring offers… {status.processed}/{status.total}
        </span>
        <div className="h-1.5 w-full overflow-hidden rounded-full bg-[var(--color-border)]">
          <div
            className="h-full rounded-full bg-[var(--color-accent)] transition-[width]"
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="card flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-3 text-sm">
      <span>
        Last run scored {status.last_scored} offer{status.last_scored === 1 ? '' : 's'}
        {status.last_failed > 0 && (
          <span className="text-[var(--color-danger)]">
            {' '}
            · {status.last_failed} failed to score
          </span>
        )}
        .
      </span>
      {status.remaining_backlog > 0 && (
        <span className="text-[var(--color-text-muted)]">
          {status.remaining_backlog} more offer{status.remaining_backlog === 1 ? '' : 's'} waiting
          to be scored — fetch again or wait for the next scheduled run.
        </span>
      )}
    </div>
  );
}
