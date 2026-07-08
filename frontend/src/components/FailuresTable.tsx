import { useState } from 'react';

import { retryFailure, type Failure, type FailureProcess } from '../api/failures';
import { failureColumns } from '../lib/failureColumns';
import { FailureDetailDrawer } from './FailureDetailDrawer';

interface FailuresTableProps {
  process: FailureProcess;
  failures: Failure[];
  loading: boolean;
  sourceLabelById: Map<number, string>;
  onRetried: (updated: Failure) => void;
}

function NoFailuresEmptyState() {
  return (
    <div className="card flex items-center justify-center py-16 text-[var(--color-text-muted)]">
      No failures recorded.
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const isResolved = status === 'resolved';
  const color = isResolved ? 'var(--color-accent)' : 'var(--color-danger)';
  return (
    <span
      className="badge"
      style={{ border: `1px solid ${color}`, color, backgroundColor: 'transparent' }}
    >
      {status}
    </span>
  );
}

export function FailuresTable({
  process,
  failures,
  loading,
  sourceLabelById,
  onRetried,
}: FailuresTableProps) {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [retryingId, setRetryingId] = useState<number | null>(null);

  if (!loading && failures.length === 0) {
    return <NoFailuresEmptyState />;
  }

  const columns = failureColumns[process];
  const selectedFailure =
    selectedId != null ? failures.find((failure) => failure.id === selectedId) : undefined;

  const handleRetry = async (failure: Failure) => {
    setRetryingId(failure.id);
    try {
      const updated = await retryFailure(process, failure.id);
      onRetried(updated);
    } finally {
      setRetryingId(null);
    }
  };

  return (
    <div className="card max-h-[70vh] overflow-y-auto">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[720px] border-collapse text-left text-sm">
          <thead className="sticky top-0 bg-[var(--color-surface)]">
            <tr className="border-b border-[var(--color-border)] text-[var(--color-text-muted)]">
              {columns.map((column) => (
                <th key={column.key} className="px-4 py-3 font-medium">
                  {column.label}
                </th>
              ))}
              <th className="px-4 py-3 font-medium">Status</th>
              <th className="px-4 py-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {failures.map((failure) => (
              <tr
                key={failure.id}
                className="cursor-pointer border-b border-[var(--color-border)] last:border-0 hover:bg-[var(--color-surface-hover)]"
                onClick={() => setSelectedId(failure.id)}
              >
                {columns.map((column) => (
                  <td key={column.key} className="px-4 py-3">
                    {column.render(failure, { sourceLabelById })}
                  </td>
                ))}
                <td className="px-4 py-3">
                  <StatusBadge status={failure.status} />
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    className="btn"
                    disabled={retryingId === failure.id}
                    onClick={(event) => {
                      event.stopPropagation();
                      void handleRetry(failure);
                    }}
                  >
                    {retryingId === failure.id ? 'Retrying…' : 'Retry'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {selectedFailure != null && (
        <FailureDetailDrawer
          process={process}
          failure={selectedFailure}
          onClose={() => setSelectedId(null)}
        />
      )}
    </div>
  );
}
