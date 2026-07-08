import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { components } from '../../api/schema';
import { SkillsTable } from './SkillsTable';

type Skill = components['schemas']['Skill'];

const skills: Skill[] = [
  { name: 'Python', hard: false },
  { name: 'Go', hard: false },
];

describe('SkillsTable', () => {
  it('renders one entry per skill with the correct values', () => {
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Skill 1 name')).toHaveValue('Python');
    expect(screen.getByLabelText('Skill 2 name')).toHaveValue('Go');
  });

  it('"Add skill" appends a new blank entry and calls onChange with the extended array', async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getByText('Add skill'));

    expect(onChange).toHaveBeenCalledWith([...skills, { name: '', hard: false }]);
  });

  it("editing an entry's name updates that field, other entries untouched", async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Skill 2 name'), '!');

    expect(onChange).toHaveBeenLastCalledWith([skills[0], { ...skills[1], name: 'Go!' }]);
  });

  it('clicking a remove button calls onChange with that entry excluded', async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getByLabelText('Remove Python'));

    expect(onChange).toHaveBeenCalledWith([skills[1]]);
  });

  it('highlights the name input for entries with a validation error', () => {
    render(<SkillsTable skills={skills} errors={[true, false]} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Skill 1 name').className).toContain(
      'border-[var(--color-danger)]',
    );
    expect(screen.getByLabelText('Skill 2 name').className).not.toContain(
      'border-[var(--color-danger)]',
    );
  });

  it('clicking the star toggle marks a skill as hard', async () => {
    const onChange = vi.fn();
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getByLabelText('Mark Python as a hard skill'));

    expect(onChange).toHaveBeenLastCalledWith([{ ...skills[0], hard: true }, skills[1]]);
  });

  it('clicking the star toggle again unmarks a hard skill', async () => {
    const onChange = vi.fn();
    const hardSkills: Skill[] = [{ name: 'Python', hard: true }, skills[1]];
    render(<SkillsTable skills={hardSkills} errors={[false, false]} onChange={onChange} />);

    await userEvent.click(screen.getByLabelText('Unmark Python as a hard skill'));

    expect(onChange).toHaveBeenLastCalledWith([{ ...hardSkills[0], hard: false }, skills[1]]);
  });

  it('renders the hard-skill helper copy explaining the veto effect', () => {
    render(<SkillsTable skills={skills} errors={[false, false]} onChange={vi.fn()} />);

    expect(
      screen.getByText(/capped at a low score, no matter how well everything else fits/i),
    ).toBeInTheDocument();
  });
});
