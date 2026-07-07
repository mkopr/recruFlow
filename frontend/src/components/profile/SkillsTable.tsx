import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type Skill = components['schemas']['Skill'];

interface SkillsTableProps {
  skills: Skill[];
  errors: boolean[];
  onChange: (next: Skill[]) => void;
}

const emptySkill = (): Skill => ({ name: '' });

export function SkillsTable({ skills, errors, onChange }: SkillsTableProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(skills, onChange, emptySkill);

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Skills</h2>
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
              className="text-xs text-[var(--color-danger)]"
              onClick={() => removeEntry(index)}
            >
              Remove
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
