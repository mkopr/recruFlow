import type { ChangeEvent } from 'react';

import type { OfferListFilters } from '../api/offers';
import { KNOWN_SOURCES, SENIORITY_LEVELS } from '../constants';
import { boolToSelectValue, selectValueToBool } from '../lib/triStateBoolean';

interface OfferFiltersProps {
  filters: OfferListFilters;
  onChange: (next: OfferListFilters) => void;
}

export function OfferFilters({ filters, onChange }: OfferFiltersProps) {
  const handleSourceChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value;
    onChange({ ...filters, source: value === '' ? undefined : value });
  };

  const handleRemoteChange = (event: ChangeEvent<HTMLSelectElement>) => {
    onChange({ ...filters, remote: selectValueToBool(event.target.value) });
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

  const handleShowAppliedChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filters, showApplied: event.target.checked });
  };

  const handleShowHiddenChange = (event: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...filters, showHidden: event.target.checked });
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
          value={boolToSelectValue(filters.remote)}
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

      <div className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        <span>Applied</span>
        <label className="input flex items-center gap-2 text-[var(--color-text)]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[var(--color-accent)]"
            checked={filters.showApplied ?? false}
            onChange={handleShowAppliedChange}
          />
          Show applied offers
        </label>
      </div>

      <div className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        <span>Visibility</span>
        <label className="input flex items-center gap-2 text-[var(--color-text)]">
          <input
            type="checkbox"
            className="h-4 w-4 accent-[var(--color-accent)]"
            checked={filters.showHidden ?? false}
            onChange={handleShowHiddenChange}
          />
          Show hidden offers
        </label>
      </div>
    </div>
  );
}
