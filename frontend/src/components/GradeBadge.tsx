import { GRADE_BADGE_CLASS, isGrade } from '../lib/grade';

interface GradeBadgeProps {
  grade: string | null | undefined;
  onClick?: () => void;
}

export function GradeBadge({ grade, onClick }: GradeBadgeProps) {
  if (grade == null || !isGrade(grade)) {
    return <span className="badge badge-grade-none">Not yet scored</span>;
  }

  const className = `badge ${GRADE_BADGE_CLASS[grade]}`;
  const ariaLabel = `Grade ${grade}, view breakdown`;

  if (onClick) {
    return (
      <button type="button" className={className} aria-label={ariaLabel} onClick={onClick}>
        {grade}
      </button>
    );
  }

  return (
    <span className={className} aria-label={ariaLabel}>
      {grade}
    </span>
  );
}
