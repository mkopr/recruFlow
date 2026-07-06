import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { GRADE_BADGE_CLASS, GRADE_ORDER } from '../lib/grade';
import { GradeBadge } from './GradeBadge';

describe('GradeBadge', () => {
  it('renders the neutral not-yet-scored state for a null grade', () => {
    render(<GradeBadge grade={null} />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders the neutral state for an undefined grade', () => {
    render(<GradeBadge grade={undefined} />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it.each(GRADE_ORDER)('renders the grade letter and matching class for %s', (grade) => {
    render(<GradeBadge grade={grade} />);

    const badge = screen.getByText(grade);
    expect(badge).toHaveClass(GRADE_BADGE_CLASS[grade]);
  });

  it('renders a clickable button and fires onClick when a grade and handler are both provided', async () => {
    const onClick = vi.fn();
    render(<GradeBadge grade="B" onClick={onClick} />);

    await userEvent.click(screen.getByRole('button'));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a non-interactive badge when a grade is present but no onClick is provided', () => {
    render(<GradeBadge grade="B" />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('B')).toBeInTheDocument();
  });

  it('treats an unrecognised grade string as the neutral not-yet-scored state', () => {
    render(<GradeBadge grade="Z" />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
  });
});
