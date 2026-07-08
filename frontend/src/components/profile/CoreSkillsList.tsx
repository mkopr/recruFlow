import { useState } from 'react';

import { useEditableList } from '../../hooks/useEditableList';

interface CoreSkillsListProps {
  coreSkills: string[];
  onChange: (next: string[]) => void;
}

export function CoreSkillsList({ coreSkills, onChange }: CoreSkillsListProps) {
  const [draft, setDraft] = useState('');
  const { removeEntry } = useEditableList(coreSkills, onChange, () => '');

  function addSkill() {
    const value = draft.trim();
    if (!value) return;
    onChange([...coreSkills, value]);
    setDraft('');
  }

  return (
    <div className="card card-accent p-4">
      <h2 className="text-lg font-semibold">Core skills</h2>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">
        Offers that mention none of these are capped at a low score, no matter how well everything
        else fits.
      </p>

      {coreSkills.length === 0 ? (
        <p className="mb-3 text-sm text-[var(--color-text-muted)]">
          Add the skills that matter most — offers missing all of them will be capped low.
        </p>
      ) : (
        <div className="mb-3 flex flex-wrap gap-2">
          {coreSkills.map((entry, index) => (
            <span key={index} className="badge gap-1 bg-[var(--color-surface-hover)]">
              {entry}
              <button
                type="button"
                aria-label={`Remove ${entry}`}
                className="text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
                onClick={() => removeEntry(index)}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="flex items-center gap-2">
        <input
          className="input flex-1"
          aria-label="New core skill"
          placeholder="e.g. Python"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              addSkill();
            }
          }}
        />
        <button type="button" className="btn btn-primary" onClick={addSkill}>
          Add core skill
        </button>
      </div>
    </div>
  );
}
