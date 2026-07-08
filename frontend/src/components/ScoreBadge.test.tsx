import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ScoreBadge } from './ScoreBadge';

describe('ScoreBadge', () => {
  it('renders the neutral not-yet-scored state for a null score', () => {
    render(<ScoreBadge scorePercent={null} />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders the neutral state for an undefined score', () => {
    render(<ScoreBadge scorePercent={undefined} />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders a distinct background color across the range red to green', () => {
    render(<ScoreBadge scorePercent={10} />);
    const low = screen.getByText('10%').style.backgroundColor;

    render(<ScoreBadge scorePercent={90} />);
    const high = screen.getByText('90%').style.backgroundColor;

    expect(low).toBeTruthy();
    expect(high).toBeTruthy();
    expect(low).not.toBe(high);
  });

  it('renders a clickable button and fires onClick when a score and handler are both provided', async () => {
    const onClick = vi.fn();
    render(<ScoreBadge scorePercent={82} onClick={onClick} />);

    await userEvent.click(screen.getByRole('button'));

    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('renders a non-interactive badge when a score is present but no onClick is provided', () => {
    render(<ScoreBadge scorePercent={82} />);

    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
  });

  it('renders 0% as scored, not as the neutral state', () => {
    render(<ScoreBadge scorePercent={0} />);

    expect(screen.getByText('0%')).toBeInTheDocument();
    expect(screen.queryByText(/not yet scored/i)).not.toBeInTheDocument();
  });
});
