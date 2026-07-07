import type { ScoringStatus } from '../api/scoring';

interface ScoringStatusBannerProps {
  status: ScoringStatus | null;
}

function RunningProgress({ processed, total }: { processed: number; total: number }) {
  const pct = total > 0 ? Math.round((processed / total) * 100) : 0;
  return (
    <div className="card flex flex-col gap-2 px-4 py-3 text-sm" role="status">
      <span>
        Scoring offers… {processed}/{total}
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

function LastRunAndBacklogSummary({ status }: { status: ScoringStatus }) {
  const hasRunBefore = status.finished_at !== null;
  const hasBacklog = status.unscored_backlog > 0;

  return (
    <div className="card flex flex-wrap items-baseline gap-x-2 gap-y-1 px-4 py-3 text-sm">
      {hasRunBefore && (
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
      )}
      {hasBacklog && (
        <span className="text-[var(--color-text-muted)]">
          {status.unscored_backlog} offer{status.unscored_backlog === 1 ? '' : 's'} not yet scored
          for the active profile — scoring runs automatically in the background.
        </span>
      )}
    </div>
  );
}

export function ScoringStatusBanner({ status }: ScoringStatusBannerProps) {
  if (status === null) {
    return null;
  }

  if (status.running) {
    return <RunningProgress processed={status.processed} total={status.total} />;
  }

  const hasAnythingToReport = status.finished_at !== null || status.unscored_backlog > 0;
  if (!hasAnythingToReport) {
    return null;
  }

  return <LastRunAndBacklogSummary status={status} />;
}
