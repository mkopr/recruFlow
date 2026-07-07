import { FetchCadenceSection } from '../components/FetchCadenceSection';
import { NotificationsSection } from '../components/NotificationsSection';
import { useScoringConfig } from '../hooks/useScoringConfig';
import type { components } from '../api/schema';

type ScoringConfigData = components['schemas']['ScoringConfig'];

const FIELDS: {
  key: keyof ScoringConfigData;
  label: string;
  errorKey: 'gradeA' | 'gradeB' | 'gradeC' | 'gradeD';
}[] = [
  { key: 'grade_a', label: 'Grade A cutoff', errorKey: 'gradeA' },
  { key: 'grade_b', label: 'Grade B cutoff', errorKey: 'gradeB' },
  { key: 'grade_c', label: 'Grade C cutoff', errorKey: 'gradeC' },
  { key: 'grade_d', label: 'Grade D cutoff', errorKey: 'gradeD' },
];

export function SettingsPage() {
  const settings = useScoringConfig();

  if (settings.loading) {
    return (
      <div className="mx-auto flex w-full max-w-screen-lg flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <p className="text-[var(--color-text-muted)]">Loading scoring config...</p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-screen-lg flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Configure the grade cutoffs used by the matcher. Thresholds must be strictly descending:
          Grade A &gt; Grade B &gt; Grade C &gt; Grade D &gt; 0.
        </p>
      </header>

      {settings.error && (
        <div className="card border-[var(--color-danger)] px-4 py-3 text-sm text-[var(--color-danger)]">
          {settings.error}
        </div>
      )}

      <div className="card flex flex-col gap-4 p-4">
        {FIELDS.map((field) => (
          <label key={field.key} className="flex flex-col gap-1 text-sm">
            {field.label}
            <input
              type="number"
              step="0.01"
              min="0"
              max="1"
              className="input"
              value={settings.config[field.key]}
              onChange={(e) =>
                settings.setConfig({
                  ...settings.config,
                  [field.key]: Number(e.target.value),
                })
              }
            />
            {settings.attemptedSubmit && settings.validationErrors[field.errorKey] && (
              <span className="text-[var(--color-danger)]">
                Must be within (0, 1] and strictly less than the grade above it.
              </span>
            )}
          </label>
        ))}
      </div>

      <div className="flex gap-3">
        <button
          type="button"
          className="btn btn-primary"
          aria-label="Save scoring config"
          disabled={settings.saving}
          onClick={() => settings.save()}
        >
          Save
        </button>
      </div>

      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Fetch cadence: how often each connector automatically checks for new offers.
        </p>
      </header>
      <FetchCadenceSection />

      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Notifications: play a sound the moment a new offer is scored Grade A.
        </p>
      </header>
      <NotificationsSection />
    </div>
  );
}
