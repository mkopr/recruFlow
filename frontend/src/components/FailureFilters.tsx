import type { FailureListFilters, FailureProcess } from '../api/failures';
import { useKnownSources } from '../hooks/useKnownSources';

interface FailureFiltersProps {
  process: FailureProcess;
  filters: FailureListFilters;
  onChange: (next: FailureListFilters) => void;
}

function IngestionFilters({ filters, onChange }: Omit<FailureFiltersProps, 'process'>) {
  const { sources: knownSources } = useKnownSources();

  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-[var(--color-text-muted)]">Source</span>
      <select
        className="input"
        value={filters.source ?? ''}
        onChange={(event) => onChange({ ...filters, source: event.target.value || undefined })}
      >
        <option value="">All sources</option>
        {knownSources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.label}
          </option>
        ))}
      </select>
    </label>
  );
}

function ScoringFilters({ filters, onChange }: Omit<FailureFiltersProps, 'process'>) {
  return (
    <>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-[var(--color-text-muted)]">Offer id</span>
        <input
          type="number"
          className="input"
          value={filters.offerId ?? ''}
          onChange={(event) =>
            onChange({
              ...filters,
              offerId: event.target.value === '' ? undefined : Number(event.target.value),
            })
          }
        />
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-[var(--color-text-muted)]">Profile id</span>
        <input
          type="number"
          className="input"
          value={filters.profileId ?? ''}
          onChange={(event) =>
            onChange({
              ...filters,
              profileId: event.target.value === '' ? undefined : Number(event.target.value),
            })
          }
        />
      </label>
    </>
  );
}

export function FailureFilters({ process, filters, onChange }: FailureFiltersProps) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-[var(--color-text-muted)]">Failure type</span>
        <input
          type="text"
          className="input"
          value={filters.failureType ?? ''}
          onChange={(event) =>
            onChange({ ...filters, failureType: event.target.value || undefined })
          }
        />
      </label>

      {process === 'ingestion' ? (
        <IngestionFilters filters={filters} onChange={onChange} />
      ) : (
        <ScoringFilters filters={filters} onChange={onChange} />
      )}

      <label className="flex flex-col gap-1 text-sm">
        <span className="text-[var(--color-text-muted)]">Status</span>
        <select
          className="input"
          value={filters.status ?? 'open'}
          onChange={(event) =>
            onChange({ ...filters, status: event.target.value as FailureListFilters['status'] })
          }
        >
          <option value="open">Open</option>
          <option value="resolved">Resolved</option>
          <option value="all">All</option>
        </select>
      </label>
    </div>
  );
}
