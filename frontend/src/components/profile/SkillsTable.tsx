import type { components } from '../../api/schema';

type Skill = components['schemas']['Skill'];

interface SkillsTableProps {
  skills: Skill[];
  errors: boolean[];
  onChange: (next: Skill[]) => void;
}

export function SkillsTable({ skills, errors, onChange }: SkillsTableProps) {
  const updateSkill = (index: number, patch: Partial<Skill>) => {
    onChange(skills.map((skill, i) => (i === index ? { ...skill, ...patch } : skill)));
  };

  const removeSkill = (index: number) => {
    onChange(skills.filter((_, i) => i !== index));
  };

  const addSkill = () => {
    onChange([...skills, { name: '', proficiency: null, years: null }]);
  };

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Skills</h2>
      <table className="w-full border-collapse text-left text-sm">
        <thead>
          <tr className="border-b border-[var(--color-border)] text-[var(--color-text-muted)]">
            <th className="px-2 py-2 font-medium">Name</th>
            <th className="px-2 py-2 font-medium">Proficiency</th>
            <th className="px-2 py-2 font-medium">Years</th>
            <th className="px-2 py-2 font-medium" />
          </tr>
        </thead>
        <tbody>
          {skills.map((skill, index) => (
            <tr key={index} className="border-b border-[var(--color-border)] last:border-0">
              <td className="px-2 py-2">
                <input
                  className={`input w-full ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
                  aria-label={`Skill ${index + 1} name`}
                  value={skill.name}
                  onChange={(e) => updateSkill(index, { name: e.target.value })}
                />
              </td>
              <td className="px-2 py-2">
                <input
                  className="input w-full"
                  aria-label={`Skill ${index + 1} proficiency`}
                  value={skill.proficiency ?? ''}
                  onChange={(e) => updateSkill(index, { proficiency: e.target.value || null })}
                />
              </td>
              <td className="px-2 py-2">
                <input
                  className="input w-full"
                  type="number"
                  aria-label={`Skill ${index + 1} years`}
                  value={skill.years ?? ''}
                  onChange={(e) =>
                    updateSkill(index, {
                      years: e.target.value === '' ? null : Number(e.target.value),
                    })
                  }
                />
              </td>
              <td className="px-2 py-2">
                <button
                  type="button"
                  className="text-xs text-[var(--color-danger)]"
                  onClick={() => removeSkill(index)}
                >
                  Remove
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" className="btn btn-primary mt-3" onClick={addSkill}>
        Add skill
      </button>
    </div>
  );
}
