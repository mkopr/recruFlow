import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type Education = components['schemas']['Education'];

interface EducationListProps {
  education: Education[];
  errors: boolean[];
  onChange: (next: Education[]) => void;
}

const emptyEducation = (): Education => ({
  institution: '',
  degree: null,
  field_of_study: null,
  start_date: null,
  end_date: null,
});

export function EducationList({ education, errors, onChange }: EducationListProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(
    education,
    onChange,
    emptyEducation,
  );

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Education</h2>
      <div className="flex flex-col gap-3">
        {education.map((entry, index) => (
          <div
            key={index}
            className="flex flex-col gap-2 border-b border-[var(--color-border)] pb-3 last:border-0"
          >
            <div className="flex flex-wrap gap-2">
              <input
                className={`input flex-1 ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
                aria-label={`Education ${index + 1} institution`}
                placeholder="Institution"
                value={entry.institution}
                onChange={(e) => updateEntry(index, { ...entry, institution: e.target.value })}
              />
              <input
                className="input flex-1"
                aria-label={`Education ${index + 1} degree`}
                placeholder="Degree"
                value={entry.degree ?? ''}
                onChange={(e) => updateEntry(index, { ...entry, degree: e.target.value || null })}
              />
              <input
                className="input flex-1"
                aria-label={`Education ${index + 1} field of study`}
                placeholder="Field of study"
                value={entry.field_of_study ?? ''}
                onChange={(e) =>
                  updateEntry(index, { ...entry, field_of_study: e.target.value || null })
                }
              />
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                className="input flex-1"
                aria-label={`Education ${index + 1} start date`}
                placeholder="Start date"
                value={entry.start_date ?? ''}
                onChange={(e) =>
                  updateEntry(index, { ...entry, start_date: e.target.value || null })
                }
              />
              <input
                className="input flex-1"
                aria-label={`Education ${index + 1} end date`}
                placeholder="End date"
                value={entry.end_date ?? ''}
                onChange={(e) => updateEntry(index, { ...entry, end_date: e.target.value || null })}
              />
            </div>
            <button
              type="button"
              className="self-start text-xs text-[var(--color-danger)]"
              onClick={() => removeEntry(index)}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
      <button type="button" className="btn btn-primary mt-3" onClick={addEntry}>
        Add education
      </button>
    </div>
  );
}
