import { useState } from 'react';

import { useOfferCleanup } from '../hooks/useOfferCleanup';

function toOlderThanParam(dateStr: string): string {
  // dateStr is "YYYY-MM-DD" from <input type="date">, which carries no timezone --
  // anchor it to UTC midnight so it's unambiguous once it reaches the API, matching
  // connectorSettingsDraft.ts's convention of always sending a UTC-anchored ISO string.
  return new Date(`${dateStr}T00:00:00Z`).toISOString();
}

export function OfferCleanupSection() {
  const {
    previewing,
    deleting,
    error,
    preview,
    result,
    loadPreview,
    confirmDelete,
    cancelPreview,
  } = useOfferCleanup();
  const [date, setDate] = useState('');

  return (
    <div className="card flex flex-col gap-4 p-4">
      {error && <div className="text-sm text-[var(--color-danger)]">{error}</div>}

      <label className="flex flex-col gap-1 text-sm">
        Delete offers posted before
        <input
          type="date"
          className="input w-48"
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </label>

      <div>
        <button
          type="button"
          className="btn"
          disabled={!date || previewing}
          onClick={() => loadPreview(toOlderThanParam(date))}
        >
          Delete offers older than this date
        </button>
      </div>

      {result && (
        <div className="text-sm">
          Deleted {result.deleted} offer(s), skipped {result.skipped} in your pipeline.
        </div>
      )}

      {preview && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Confirm offer cleanup"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
          onClick={cancelPreview}
        >
          <div className="card max-w-md p-6" onClick={(event) => event.stopPropagation()}>
            <p className="text-sm">
              This will delete {preview.wouldDelete} offer(s). {preview.wouldSkip} offer(s) will be
              skipped because they're in your pipeline.
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button type="button" className="btn" onClick={cancelPreview} disabled={deleting}>
                Cancel
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={deleting}
                onClick={() => confirmDelete(toOlderThanParam(date))}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
