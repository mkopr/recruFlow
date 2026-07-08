import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CoreSkillsList } from './CoreSkillsList';

describe('CoreSkillsList', () => {
  it('renders existing core-skill chips from props', () => {
    render(<CoreSkillsList coreSkills={['Python', 'Go']} onChange={vi.fn()} />);

    expect(screen.getByText('Python')).toBeInTheDocument();
    expect(screen.getByText('Go')).toBeInTheDocument();
  });

  it('adding a skill via the add-input calls onChange with the new list appended', async () => {
    const onChange = vi.fn();
    render(<CoreSkillsList coreSkills={['Python']} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('New core skill'), 'Go');
    await userEvent.click(screen.getByRole('button', { name: 'Add core skill' }));

    expect(onChange).toHaveBeenLastCalledWith(['Python', 'Go']);
  });

  it('removing a chip calls onChange with that entry excluded', async () => {
    const onChange = vi.fn();
    render(<CoreSkillsList coreSkills={['Python', 'Go']} onChange={onChange} />);

    await userEvent.click(screen.getByLabelText('Remove Python'));

    expect(onChange).toHaveBeenLastCalledWith(['Go']);
  });

  it('renders an inviting empty state when coreSkills is empty', () => {
    render(<CoreSkillsList coreSkills={[]} onChange={vi.fn()} />);

    expect(screen.getByText(/add the skills that matter most/i)).toBeInTheDocument();
  });

  it('renders the hard-veto helper copy regardless of list state', () => {
    render(<CoreSkillsList coreSkills={['Python']} onChange={vi.fn()} />);

    expect(
      screen.getByText(/capped at a low score, no matter how well everything else fits/i),
    ).toBeInTheDocument();
  });
});
