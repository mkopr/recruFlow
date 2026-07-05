export interface EditableList<T> {
  addEntry: () => void;
  removeEntry: (index: number) => void;
  updateEntry: (index: number, value: T) => void;
}

export function useEditableList<T>(
  items: T[],
  onChange: (next: T[]) => void,
  createEntry: () => T,
): EditableList<T> {
  return {
    addEntry: () => onChange([...items, createEntry()]),
    removeEntry: (index) => onChange(items.filter((_, i) => i !== index)),
    updateEntry: (index, value) => onChange(items.map((item, i) => (i === index ? value : item))),
  };
}
