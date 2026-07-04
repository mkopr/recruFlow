import type { ChangeEvent } from 'react';

import type { components } from '../../api/schema';
import { boolToSelectValue, selectValueToBool } from '../../lib/triStateBoolean';

type ProfileData = components['schemas']['Profile'];

interface PreferencesFieldsProps {
  profile: ProfileData;
  onChange: (next: ProfileData) => void;
}

export function PreferencesFields({ profile, onChange }: PreferencesFieldsProps) {
  const handleContractTypeChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...profile, contract_type_preference: e.target.value || null });
  };

  const handleSalaryMinChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({
      ...profile,
      salary_min: e.target.value === '' ? null : Number(e.target.value),
    });
  };

  const handleSalaryTargetChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({
      ...profile,
      salary_target: e.target.value === '' ? null : Number(e.target.value),
    });
  };

  const handleLocationChange = (e: ChangeEvent<HTMLInputElement>) => {
    onChange({ ...profile, location_preference: e.target.value || null });
  };

  const handleRemoteChange = (e: ChangeEvent<HTMLSelectElement>) => {
    onChange({ ...profile, remote_preference: selectValueToBool(e.target.value) ?? null });
  };

  return (
    <div className="card flex flex-col gap-4 p-4">
      <h2 className="text-lg font-semibold">Preferences</h2>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Contract type
        <input
          className="input"
          value={profile.contract_type_preference ?? ''}
          onChange={handleContractTypeChange}
        />
      </label>

      <div className="flex flex-wrap gap-4">
        <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
          Salary range (PLN) — min
          <input
            className="input"
            type="number"
            value={profile.salary_min ?? ''}
            onChange={handleSalaryMinChange}
          />
        </label>
        <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
          Salary range (PLN) — target
          <input
            className="input"
            type="number"
            value={profile.salary_target ?? ''}
            onChange={handleSalaryTargetChange}
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Location preference
        <input
          className="input"
          value={profile.location_preference ?? ''}
          onChange={handleLocationChange}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
        Remote
        <select
          className="input"
          value={boolToSelectValue(profile.remote_preference)}
          onChange={handleRemoteChange}
        >
          <option value="">Any</option>
          <option value="true">Remote</option>
          <option value="false">On-site</option>
        </select>
      </label>
    </div>
  );
}
