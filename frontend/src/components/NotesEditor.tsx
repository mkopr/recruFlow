import { useEffect, useState } from 'react';

interface NotesEditorProps {
  offerTitle: string;
  initialNotes: string | null;
  onSave: (notes: string) => Promise<void>;
  onClose: () => void;
}

export function NotesEditor({ offerTitle, initialNotes, onSave, onClose }: NotesEditorProps) {
  const [value, setValue] = useState(initialNotes ?? '');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        onClose();
      }
    }

    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [onClose]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(value);
      onClose();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={`Notes for ${offerTitle}`}
        className="card h-full w-full max-w-md overflow-y-auto p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-semibold">{offerTitle}</h2>
        <textarea
          className="input mt-4 h-64 w-full"
          value={value}
          onChange={(event) => setValue(event.target.value)}
        />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" className="btn" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button type="button" className="btn" onClick={handleSave} disabled={saving}>
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
