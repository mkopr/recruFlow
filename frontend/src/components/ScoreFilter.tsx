import type { ChangeEvent } from 'react';

interface ScoreFilterProps {
  value: number | '';
  onChange: (next: number | '') => void;
}

export function ScoreFilter({ value, onChange }: ScoreFilterProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const raw = event.target.value;
    if (raw === '') {
      onChange('');
      return;
    }
    const parsed = Number(raw);
    onChange(Number.isNaN(parsed) ? '' : parsed);
  };

  return (
    <label className="flex flex-col gap-1 text-sm text-[var(--color-text-muted)]">
      Minimum score %
      <input
        type="number"
        min={0}
        max={100}
        step={1}
        className="input"
        value={value}
        onChange={handleChange}
        placeholder="Any"
      />
    </label>
  );
}
