import type { SourceStatus } from '../api/scheduler';
import { KNOWN_SOURCES } from '../constants';

interface SourceStatusListProps {
  sources: SourceStatus[];
}

function formatLastFetchedAt(value: string | null): string {
  return value === null ? 'Never fetched' : new Date(value).toLocaleString();
}

export function SourceStatusList({ sources }: SourceStatusListProps) {
  const byConnector = new Map(sources.map((source) => [source.connector, source]));

  return (
    <div className="card flex flex-wrap gap-x-6 gap-y-1 px-4 py-3 text-sm">
      {KNOWN_SOURCES.map((source) => (
        <span key={source.id} className="text-[var(--color-text-muted)]">
          <span className="font-medium text-[var(--color-text)]">{source.label}:</span>{' '}
          {formatLastFetchedAt(byConnector.get(source.id)?.last_fetched_at ?? null)}
        </span>
      ))}
    </div>
  );
}
