import { useEditableList } from '../../hooks/useEditableList';

interface DealBreakersListProps {
  dealBreakers: string[];
  onChange: (next: string[]) => void;
}

const emptyDealBreaker = (): string => '';

export function DealBreakersList({ dealBreakers, onChange }: DealBreakersListProps) {
  const { updateEntry, removeEntry, addEntry } = useEditableList(
    dealBreakers,
    onChange,
    emptyDealBreaker,
  );

  return (
    <div className="card p-4">
      <h2 className="mb-3 text-lg font-semibold">Deal breakers</h2>
      <div className="flex flex-col gap-2">
        {dealBreakers.map((entry, index) => (
          <div key={index} className="flex items-center gap-2">
            <input
              className="input flex-1"
              aria-label={`Deal breaker ${index + 1}`}
              value={entry}
              onChange={(e) => updateEntry(index, e.target.value)}
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
        Add deal breaker
      </button>
    </div>
  );
}
