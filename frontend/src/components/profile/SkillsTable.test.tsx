import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { SkillsTable } from './SkillsTable';

type Skill = components['schemas']['Skill'];

const skills: Skill[] = [
  { name: 'Python', proficiency: 'senior', years: 5 },
  { name: 'Go', proficiency: null, years: null },
];

describe('SkillsTable', () => {
  it('renders one row per skill with the correct values', () => {
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python');
    expect(screen.getByLabelText('Skill 1 proficiency')).toHaveValue('senior');
    expect(screen.getByLabelText('Skill 1 years')).toHaveValue(5);
    expect(screen.getByLabelText('Skill 2 name')).toHaveValue('Go');
    expect(screen.getByLabelText('Skill 2 proficiency')).toHaveValue('');
  });

  it('"Add skill" appends a new blank row and calls onChange with the extended array', async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getByText('Add skill'));

    expect(onChange).toHaveBeenCalledWith([
      ...skills,
      { name: '', proficiency: null, years: null },
    ]);
  });

  it("editing a row's name updates that field, other rows untouched", async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Skill 2 name'), '!');

    expect(onChange).toHaveBeenLastCalledWith([skills[0], { ...skills[1], name: 'Go!' }]);
  });

  it('clicking a remove button calls onChange with that row excluded', async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getAllByText('Remove')[0]);

    expect(onChange).toHaveBeenCalledWith([skills[1]]);
  });

  it('highlights the name input for rows with a validation error', () => {
    render(<SkillsTable skills={skills} errors={[true, false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Skill 1 name').className).toContain(
      'border-[var(--color-danger)]',
    );
    expect(screen.getByLabelText('Skill 2 name').className).not.toContain(
      'border-[var(--color-danger)]',
    );
  });
});
