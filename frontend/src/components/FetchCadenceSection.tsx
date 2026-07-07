import { useState } from 'react';

import { useFetchCadence } from '../hooks/useFetchCadence';
import { KNOWN_SOURCES } from '../constants';

function secondsToMinutes(seconds: unknown): number {
  return typeof seconds === 'number' ? seconds / 60 : 5;
}

export function FetchCadenceSection() {
  const cadence = useFetchCadence();
  const [applyAllMinutes, setApplyAllMinutes] = useState(5);
  const [minutesByConnector, setMinutesByConnector] = useState<Record<string, number>>({});

  const minutesFor = (connector: string, currentSeconds: unknown): number =>
    minutesByConnector[connector] ?? secondsToMinutes(currentSeconds);

  return (
    <div className="card flex flex-col gap-4 p-4">
      {cadence.error && <div className="text-sm text-[var(--color-danger)]">{cadence.error}</div>}

      {KNOWN_SOURCES.map((known) => {
        const status = cadence.sources.find((source) => source.connector === known.id);
        const minutes = minutesFor(known.id, status?.schedule?.seconds);
        const isSaving = cadence.saving[known.id] ?? false;

        return (
          <div key={known.id} className="flex items-center gap-3">
            <span className="w-32 text-sm font-medium">{known.label}</span>
            <input
              type="number"
              min="1"
              step="1"
              className="input w-24"
              value={minutes}
              onChange={(e) =>
                setMinutesByConnector((prev) => ({
                  ...prev,
                  [known.id]: Number(e.target.value),
                }))
              }
            />
            <span className="text-xs text-[var(--color-text-muted)]">minutes</span>
            <button
              type="button"
              className="btn"
              disabled={isSaving}
              onClick={() => cadence.saveOne(known.id, Math.round(minutes * 60))}
            >
              {isSaving ? 'Saving…' : 'Save'}
            </button>
          </div>
        );
      })}

      <div className="mt-2 flex items-center gap-3 border-t border-[var(--color-border)] pt-4">
        <span className="w-32 text-sm font-medium">Apply to all</span>
        <input
          type="number"
          min="1"
          step="1"
          className="input w-24"
          value={applyAllMinutes}
          onChange={(e) => setApplyAllMinutes(Number(e.target.value))}
        />
        <span className="text-xs text-[var(--color-text-muted)]">minutes</span>
        <button
          type="button"
          className="btn btn-primary"
          onClick={() => cadence.saveAll(Math.round(applyAllMinutes * 60))}
        >
          Apply to all
        </button>
      </div>
    </div>
  );
}
