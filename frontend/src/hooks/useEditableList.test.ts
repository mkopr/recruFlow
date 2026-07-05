import { describe, expect, it, vi } from 'vitest';

import { useEditableList } from './useEditableList';

interface Row {
  name: string;
  value: number | null;
}

const emptyRow = (): Row => ({ name: '', value: null });

describe('useEditableList', () => {
  it('addEntry appends a new entry created by the factory', () => {
    const onChange = vi.fn();
    const items: Row[] = [{ name: 'a', value: 1 }];

    useEditableList(items, onChange, emptyRow).addEntry();

    expect(onChange).toHaveBeenCalledWith([{ name: 'a', value: 1 }, emptyRow()]);
  });

  it('removeEntry excludes the entry at the given index', () => {
    const onChange = vi.fn();
    const items: Row[] = [
      { name: 'a', value: 1 },
      { name: 'b', value: 2 },
    ];

    useEditableList(items, onChange, emptyRow).removeEntry(0);

    expect(onChange).toHaveBeenCalledWith([{ name: 'b', value: 2 }]);
  });

  it('updateEntry replaces only the entry at the given index', () => {
    const onChange = vi.fn();
    const items: Row[] = [
      { name: 'a', value: 1 },
      { name: 'b', value: 2 },
    ];

    useEditableList(items, onChange, emptyRow).updateEntry(1, { name: 'b!', value: 2 });

    expect(onChange).toHaveBeenCalledWith([
      { name: 'a', value: 1 },
      { name: 'b!', value: 2 },
    ]);
  });

  it('works over primitive arrays, not just objects', () => {
    const onChange = vi.fn();
    const items = ['x', 'y'];
    const list = useEditableList(items, onChange, () => '');

    list.updateEntry(0, 'x!');
    expect(onChange).toHaveBeenLastCalledWith(['x!', 'y']);

    list.addEntry();
    expect(onChange).toHaveBeenLastCalledWith(['x', 'y', '']);

    list.removeEntry(1);
    expect(onChange).toHaveBeenLastCalledWith(['x']);
  });

  it('leaves the source array untouched (immutable)', () => {
    const onChange = vi.fn();
    const items: Row[] = [{ name: 'a', value: 1 }];

    useEditableList(items, onChange, emptyRow).addEntry();

    expect(items).toEqual([{ name: 'a', value: 1 }]);
  });
});
