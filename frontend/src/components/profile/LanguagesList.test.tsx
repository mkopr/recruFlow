import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { LanguagesList } from './LanguagesList';

type Language = components['schemas']['Language'];

const languages: Language[] = [{ name: 'English' }];

describe('LanguagesList', () => {
  it('renders existing entries correctly', () => {
    render(<LanguagesList languages={languages} errors={[false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Language 1 name')).toHaveValue('English');
  });

  it('editing a field updates it immutably', async () => {
    const onChange = vi.fn();
    render(<LanguagesList languages={languages} errors={[false]} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Language 1 name'), '!');

    expect(onChange).toHaveBeenLastCalledWith([{ ...languages[0], name: 'English!' }]);
  });

  it('highlights name for a flagged entry', () => {
    render(<LanguagesList languages={languages} errors={[true]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Language 1 name').className).toContain(
      'border-[var(--color-danger)]',
    );
  });
});
