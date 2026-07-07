import type { components } from '../../api/schema';
import { useEditableList } from '../../hooks/useEditableList';

type Language = components['schemas']['Language'];

interface LanguagesListProps {
  languages: Language[];
  errors: boolean[];
  onChange: (next: Language[]) => void;
}

const emptyLanguage = (): Language => ({ name: '' });

export function LanguagesList({ languages, errors, onChange }: LanguagesListProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(
    languages,
    onChange,
    emptyLanguage,
  );

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Languages</h2>
      <div className="flex flex-wrap gap-2">
        {languages.map((entry, index) => (
          <div key={index} className="flex items-center gap-1">
            <input
              className={`input w-32 ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
              aria-label={`Language ${index + 1} name`}
              placeholder="Name"
              value={entry.name}
              onChange={(e) => updateEntry(index, { ...entry, name: e.target.value })}
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
