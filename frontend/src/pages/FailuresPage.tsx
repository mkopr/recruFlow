import { useState } from 'react';

import type { FailureListFilters, FailureProcess } from '../api/failures';
import { FailureFilters } from '../components/FailureFilters';
import { FailuresTable } from '../components/FailuresTable';
import { useFailures } from '../hooks/useFailures';
import { useSchedulerStatus } from '../hooks/useSchedulerStatus';

const PAGE_SIZE = 50;

const PROCESS_OPTIONS: { id: FailureProcess; label: string }[] = [
  { id: 'ingestion', label: 'Ingestion' },
  { id: 'scoring', label: 'Scoring' },
];

export function FailuresPage() {
  const [process, setProcess] = useState<FailureProcess>('ingestion');
  const [filters, setFilters] = useState<FailureListFilters>({ status: 'open' });
  const [page, setPage] = useState(0);

  const { failures, total, loading, error, refetch } = useFailures(process, filters, {
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
  });
  const { sources } = useSchedulerStatus();
  const sourceLabelById = new Map(sources.map((source) => [source.source_id, source.connector]));

  const handleProcessChange = (next: FailureProcess) => {
    setPage(0);
    setProcess(next);
    setFilters({ status: 'open' });
  };

  const handleFiltersChange = (next: FailureListFilters) => {
    setPage(0);
    setFilters(next);
  };

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto flex w-full max-w-screen-2xl flex-col gap-4 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <div className="flex flex-wrap gap-2">
        {PROCESS_OPTIONS.map((option) => (
          <button
            key={option.id}
            type="button"
            className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
              process === option.id
                ? 'bg-[var(--color-surface)] text-[var(--color-text)]'
                : 'text-[var(--color-text-muted)] hover:text-[var(--color-text)]'
            }`}
            onClick={() => handleProcessChange(option.id)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <FailureFilters process={process} filters={filters} onChange={handleFiltersChange} />

      {error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {error}
        </div>
      )}

      <FailuresTable
        process={process}
        failures={failures}
        loading={loading}
        sourceLabelById={sourceLabelById}
        onRetried={refetch}
      />

      {total > 0 && (
        <div className="flex items-center justify-between text-sm text-[var(--color-text-muted)]">
          <span>
            {total.toLocaleString('en-US')} failure{total === 1 ? '' : 's'}, page {page + 1} of{' '}
            {pageCount}
          </span>
          <div className="flex gap-2">
            <button
              type="button"
              className="btn"
              disabled={page === 0}
              onClick={() => setPage((current) => Math.max(0, current - 1))}
            >
              Previous
            </button>
            <button
              type="button"
              className="btn"
              disabled={page + 1 >= pageCount}
              onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
