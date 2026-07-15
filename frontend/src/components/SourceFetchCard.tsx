import { useState } from 'react';

import { triggerIngest } from '../api/offers';

interface SourceFetchCardProps {
  source: string;
  label: string;
  lastFetchedAt: string | null;
  offerCount: number;
  scoredCount: number;
  unscoredCount: number;
  onIngested: () => void;
}

function formatLastFetchedAt(value: string | null): string {
  return value === null ? 'Never fetched' : new Date(value).toLocaleString();
}

export function SourceFetchCard({
  source,
  label,
  lastFetchedAt,
  offerCount,
  scoredCount,
  onIngested,
}: SourceFetchCardProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  const handleClick = async () => {
    if (loading) return;

    setLoading(true);
    setError(null);
    setSummary(null);
    try {
      const result = await triggerIngest(source);
      if (result.ok) {
        setSummary(`Fetched ${result.fetched}, ${result.created} new`);
        onIngested();
      } else {
        setError(result.error_message ?? 'ingestion failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to trigger ingest');
    } finally {
      setLoading(false);
    }
  };

  const status = loading ? 'Fetching…' : (error ?? summary ?? formatLastFetchedAt(lastFetchedAt));

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={loading}
      title={label}
      className="card card-interactive flex min-w-0 flex-1 flex-col items-start gap-0.5 px-3 py-3 text-left"
    >
      <span className="w-full truncate text-xs font-medium">{label}</span>
      <span
        className={
          error
            ? 'w-full truncate text-[10px] text-[var(--color-danger)]'
            : 'w-full truncate text-[10px] text-[var(--color-text-muted)] opacity-70'
        }
      >
        {status}
      </span>
      <span className="text-[10px] text-[var(--color-text-muted)] opacity-70">
        {scoredCount} / {offerCount}
      </span>
    </button>
  );
}
