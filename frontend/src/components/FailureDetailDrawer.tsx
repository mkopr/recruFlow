import { useEffect } from 'react';

import type { Failure, FailureProcess, IngestionFailure, ScoringFailure } from '../api/failures';

interface FailureDetailDrawerProps {
  process: FailureProcess;
  failure: Failure;
  onClose: () => void;
}

function originLabel(process: FailureProcess, failure: Failure): string {
  if (process === 'ingestion') {
    const ingestionFailure = failure as IngestionFailure;
    return ingestionFailure.scheduler_run_id != null
      ? `Scheduler run #${ingestionFailure.scheduler_run_id}`
      : 'Manual trigger';
  }
  const scoringFailure = failure as ScoringFailure;
  return `Offer #${scoringFailure.offer_id}, Profile #${scoringFailure.profile_id}`;
}

export function FailureDetailDrawer({ process, failure, onClose }: FailureDetailDrawerProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`${failure.failure_type} failure`}
        className="card h-full w-full max-w-md overflow-y-auto p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{failure.failure_type}</h2>
            <p className="mt-1 text-sm text-[var(--color-text-muted)]">
              {originLabel(process, failure)}
            </p>
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>

        <p className="mt-4 whitespace-pre-wrap text-sm text-[var(--color-text)]">
          {failure.error_message}
        </p>

        {failure.raw_payload != null && (
          <pre className="mt-4 overflow-x-auto rounded bg-[var(--color-surface-hover)] p-3 text-xs">
            {JSON.stringify(failure.raw_payload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  );
}
