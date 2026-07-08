import { useEffect } from 'react';

import type { MatchScoreResponse } from '../api/offerScore';
import { ScoreBadge } from './ScoreBadge';

interface ScoreDrawerProps {
  score: MatchScoreResponse;
  offerTitle: string;
  onClose: () => void;
}

function titleCase(key: string): string {
  return key
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function ScoreDrawer({ score, offerTitle, onClose }: ScoreDrawerProps) {
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
        aria-label={offerTitle}
        className="card h-full w-full max-w-md overflow-y-auto p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-lg font-semibold">{offerTitle}</h2>
            <div className="mt-2">
              <ScoreBadge scorePercent={score.score_percent} />
            </div>
          </div>
          <button type="button" className="btn" onClick={onClose} aria-label="Close">
            Close
          </button>
        </div>

        <p className="mt-4 text-sm text-[var(--color-text-muted)]">
          {score.rationale ?? 'No rationale recorded.'}
        </p>

        <ul className="mt-4 flex flex-col gap-2">
          {Object.entries(score.dimensions).map(([dimension, value]) => (
            <li key={dimension} className="flex items-center justify-between text-sm">
              <span>{titleCase(dimension)}</span>
              <span className="text-[var(--color-text-muted)]">{Math.round(value * 100)}%</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
