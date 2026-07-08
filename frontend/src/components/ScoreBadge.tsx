import { scoreBadgeColor } from '../lib/scoreColor';

interface ScoreBadgeProps {
  scorePercent: number | null | undefined;
  onClick?: () => void;
}

export function ScoreBadge({ scorePercent, onClick }: ScoreBadgeProps) {
  if (scorePercent == null) {
    return <span className="badge badge-score-none">Not yet scored</span>;
  }

  const style = { backgroundColor: scoreBadgeColor(scorePercent) };
  const label = `${scorePercent}%`;
  const ariaLabel = `Score ${scorePercent}%, view breakdown`;

  if (onClick) {
    return (
      <button
        type="button"
        className="badge badge-score"
        style={style}
        aria-label={ariaLabel}
        onClick={onClick}
      >
        {label}
      </button>
    );
  }

  return (
    <span className="badge badge-score" style={style} aria-label={ariaLabel}>
      {label}
    </span>
  );
}
