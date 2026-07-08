import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { NotesEditor } from './NotesEditor';

describe('NotesEditor', () => {
  it('prefills the textarea with initialNotes', () => {
    render(
      <NotesEditor
        offerTitle="Senior Backend Engineer"
        initialNotes="existing notes"
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByRole('textbox')).toHaveValue('existing notes');
  });

  it('calls onSave with the edited value then onClose', async () => {
    const onSave = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(
      <NotesEditor offerTitle="Offer" initialNotes={null} onSave={onSave} onClose={onClose} />,
    );

    await userEvent.type(screen.getByRole('textbox'), 'new notes');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    expect(onSave).toHaveBeenCalledWith('new notes');
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose without onSave when Cancel is clicked', async () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <NotesEditor offerTitle="Offer" initialNotes={null} onSave={onSave} onClose={onClose} />,
    );

    await userEvent.click(screen.getByRole('button', { name: /cancel/i }));

    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('closes on Escape without calling onSave', () => {
    const onSave = vi.fn();
    const onClose = vi.fn();
    render(
      <NotesEditor offerTitle="Offer" initialNotes={null} onSave={onSave} onClose={onClose} />,
    );

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onSave).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
