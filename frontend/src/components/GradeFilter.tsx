import type { ChangeEvent } from 'react';

import { GRADE_ORDER, type Grade } from '../lib/grade';

interface GradeFilterProps {
  value: Grade | '';
  onChange: (next: Grade | '') => void;
}

export function GradeFilter({ value, onChange }: GradeFilterProps) {
  const handleChange = (event: ChangeEvent<HTMLSelectElement>) => {
    const next = event.target.value;
    onChange(next === '' ? '' : (next as Grade));
  };

  return (
    <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
      Minimum grade
      <select className="input" value={value} onChange={handleChange}>
        <option value="">Any</option>
        {GRADE_ORDER.map((grade) => (
          <option key={grade} value={grade}>
            {grade}
          </option>
        ))}
      </select>
    </label>
  );
}
