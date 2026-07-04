import type { components } from '../../api/schema';

type Certification = components['schemas']['Certification'];

interface CertificationsListProps {
  certifications: Certification[];
  errors: boolean[];
  onChange: (next: Certification[]) => void;
}

export function CertificationsList({ certifications, errors, onChange }: CertificationsListProps) {
  const updateEntry = (index: number, patch: Partial<Certification>) => {
    onChange(certifications.map((entry, i) => (i === index ? { ...entry, ...patch } : entry)));
  };

  const removeEntry = (index: number) => {
    onChange(certifications.filter((_, i) => i !== index));
  };

  const addEntry = () => {
    onChange([...certifications, { name: '', issuer: null, year: null }]);
  };

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Certifications</h2>
      <div className="flex flex-col gap-3">
        {certifications.map((entry, index) => (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <input
              className={`input flex-1 ${errors[index] ? 'border-[var(--color-danger)]' : ''}`}
              aria-label={`Certification ${index + 1} name`}
              placeholder="Name"
              value={entry.name}
              onChange={(e) => updateEntry(index, { name: e.target.value })}
            />
            <input
              className="input flex-1"
              aria-label={`Certification ${index + 1} issuer`}
              placeholder="Issuer"
              value={entry.issuer ?? ''}
              onChange={(e) => updateEntry(index, { issuer: e.target.value || null })}
            />
            <input
              className="input w-28"
              type="number"
              aria-label={`Certification ${index + 1} year`}
              placeholder="Year"
              value={entry.year ?? ''}
              onChange={(e) =>
                updateEntry(index, { year: e.target.value === '' ? null : Number(e.target.value) })
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
        Add certification
      </button>
    </div>
  );
}
