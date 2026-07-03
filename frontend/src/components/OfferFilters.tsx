import type { ChangeEvent } from 'react';

import type { OfferListFilters } from '../api/offers';
import { KNOWN_SOURCES, SENIORITY_LEVELS } from '../constants';

interface OfferFiltersProps {
  filters: OfferListFilters;
  onChange: (next: OfferListFilters) => void;
}

function remoteToSelectValue(remote: boolean | undefined): '' | 'true' | 'false' {
  if (remote === undefined) return '';
  return remote ? 'true' : 'false';
}

function selectValueToRemote(value: string): boolean | undefined {
  if (value === 'true') return true;
  if (value === 'false') return false;
  return undefined;
}

export function OfferFilters({ filters, onChange }: OfferFiltersProps) {
  const handleSourceChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    onChange({ ...filters, source: value === '' ? undefined : value });
  };

  const handleRemoteChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange({ ...filters, remote: selectValueToRemote(event.target.value) });
  };

  const handleSeniorityChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    onChange({ ...filters, seniority: value === '' ? undefined : value });
  };

  const handleMinSalaryChange = (event: ChangeEvent<HTMLInputElement>) => {
    const raw = event.target.value;
    if (raw === '') {
      onChange({ ...filters, minSalary: undefined });
      return;
    }
    const parsed = Math.max(0, Number(raw));
    onChange({ ...filters, minSalary: parsed });
  };

  return (
    <div className="flex flex-wrap items-end gap-4">
      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Source
        <select className="input" value={filters.source ?? ''} onChange={handleSourceChange}>
          <option value="">All sources</option>
          {KNOWN_SOURCES.map((source) => (
            <option key={source.id} value={source.id}>
              {source.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Remote
        <select
          className="input"
          value={remoteToSelectValue(filters.remote)}
          onChange={handleRemoteChange}
        >
          <option value="">Any</option>
          <option value="true">Remote</option>
          <option value="false">On-site</option>
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Seniority
        <select className="input" value={filters.seniority ?? ''} onChange={handleSeniorityChange}>
          <option value="">Any</option>
          {SENIORITY_LEVELS.map((level) => (
            <option key={level} value={level}>
              {level}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Min salary (PLN)
        <input
          className="input"
          type="number"
          min={0}
          placeholder="e.g. 15000"
          value={filters.minSalary ?? ''}
          onChange={handleMinSalaryChange}
        />
      </label>
    </div>
  );
}
