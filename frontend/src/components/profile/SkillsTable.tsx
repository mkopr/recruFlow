import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type Skill = components['schemas']['Skill'];

interface SkillsTableProps {
  skills: Skill[];
  errors: boolean[];
  onChange: (next: Skill[]) => void;
}

const emptySkill = (): Skill => ({ name: '', hard: false });

export function SkillsTable({ skills, errors, onChange }: SkillsTableProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(skills, onChange, emptySkill);

  return (
    <div className="card p-4">
      <h2 className="text-lg font-semibold">Skills</h2>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">
        Star a skill to mark it as required. Offers mentioning none of your starred skills are
        capped at a low score, no matter how well everything else fits.
      </p>
      <div className="flex flex-wrap gap-2">
        {skills.map((skill, index) => (
          <div key={index} className="flex items-center gap-1">
            <input
              className={`input w-32 ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
              aria-label={`Skill ${index + 1} name`}
              value={skill.name}
              onChange={(e) => updateEntry(index, { ...skill, name: e.target.value })}
            />
            <button
              type="button"
              aria-pressed={skill.hard}
              aria-label={
                skill.hard
                  ? `Unmark ${skill.name || `skill ${index + 1}`} as a hard skill`
                  : `Mark ${skill.name || `skill ${index + 1}`} as a hard skill`
              }
              title="Hard skill: offers missing every hard skill are capped at a low score"
              className={
                skill.hard
                  ? 'text-[var(--color-accent)]'
                  : 'text-[var(--color-text-muted)] hover:text-[var(--color-accent)]'
              }
              onClick={() => updateEntry(index, { ...skill, hard: !skill.hard })}
            >
              {skill.hard ? '★' : '☆'}
            </button>
            <button
              type="button"
              aria-label={`Remove ${skill.name || `skill ${index + 1}`}`}
              className="text-[var(--color-text-muted)] hover:text-[var(--color-danger)]"
              onClick={() => removeEntry(index)}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      <button type="button" className="btn btn-primary mt-3" onClick={addEntry}>
        Add skill
      </button>
    </div>
  );
}
