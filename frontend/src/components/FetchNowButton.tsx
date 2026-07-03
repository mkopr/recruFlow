import { useState } from 'react';

import { triggerIngest } from '../api/offers';

interface FetchNowButtonProps {
  source: string;
  label: string;
  onIngested: () => void;
}

export function FetchNowButton({ source, label, onIngested }: FetchNowButtonProps) {
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

  return (
    <div className="flex flex-col gap-1">
      <button type="button" className="btn btn-primary" onClick={handleClick} disabled={loading}>
        {loading ? 'Fetching...' : label}
      </button>
      {summary && <span className="text-xs text-[var(--color-text-muted)]">{summary}</span>}
      {error && <span className="text-xs text-[var(--color-danger)]">{error}</span>}
    </div>
  );
}
