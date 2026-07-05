import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type Language = components['schemas']['Language'];

interface LanguagesListProps {
  languages: Language[];
  errors: boolean[];
  onChange: (next: Language[]) => void;
}

const emptyLanguage = (): Language => ({ name: '', proficiency: null });

export function LanguagesList({ languages, errors, onChange }: LanguagesListProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(
    languages,
    onChange,
    emptyLanguage,
  );

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Languages</h2>
      <div className="flex flex-col gap-3">
        {languages.map((entry, index) => (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <input
              className={`input flex-1 ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
              aria-label={`Language ${index + 1} name`}
              placeholder="Name"
              value={entry.name}
              onChange={(e) => updateEntry(index, { ...entry, name: e.target.value })}
            />
            <input
              className="input flex-1"
              aria-label={`Language ${index + 1} proficiency`}
              placeholder="Proficiency"
              value={entry.proficiency ?? ''}
              onChange={(e) =>
                updateEntry(index, { ...entry, proficiency: e.target.value || null })
              }
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
        Add language
      </button>
    </div>
  );
}
