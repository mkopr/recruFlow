import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { MatchScoreResponse } from '../api/offerScore';
import { ScoreDrawer } from './ScoreDrawer';

function makeScore(overrides: Partial<MatchScoreResponse> = {}): MatchScoreResponse {
  return {
    id: 1,
    offer_id: 1,
    profile_id: 1,
    engine: 'langchain',
    score_percent: 92,
    dimensions: { skill_match: 0.8, salary_fit: 0.55 },
    rationale: 'Strong match on core skills.',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

describe('ScoreDrawer', () => {
  it('renders the rationale and offer title', () => {
    render(
      <ScoreDrawer score={makeScore()} offerTitle="Senior Backend Engineer" onClose={vi.fn()} />,
    );

    expect(screen.getByText('Senior Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Strong match on core skills.')).toBeInTheDocument();
  });

  it('renders every dimension with a formatted percentage', () => {
    render(
      <ScoreDrawer
        score={makeScore({ dimensions: { skill_match: 0.8, salary_fit: 0.55 } })}
        offerTitle="Offer"
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText('Skill Match')).toBeInTheDocument();
    expect(screen.getByText('80%')).toBeInTheDocument();
    expect(screen.getByText('Salary Fit')).toBeInTheDocument();
    expect(screen.getByText('55%')).toBeInTheDocument();
  });

  it('falls back to a placeholder when rationale is null', () => {
    render(
      <ScoreDrawer score={makeScore({ rationale: null })} offerTitle="Offer" onClose={vi.fn()} />,
    );

    expect(screen.getByText('No rationale recorded.')).toBeInTheDocument();
  });

  it('calls onClose when the backdrop is clicked', async () => {
    const onClose = vi.fn();
    render(<ScoreDrawer score={makeScore()} offerTitle="Offer" onClose={onClose} />);

    await userEvent.click(screen.getByRole('dialog').parentElement as HTMLElement);

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('calls onClose when Escape is pressed', () => {
    const onClose = vi.fn();
    render(<ScoreDrawer score={makeScore()} offerTitle="Offer" onClose={onClose} />);

    fireEvent.keyDown(window, { key: 'Escape' });

    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('exposes an accessible dialog role', () => {
    render(<ScoreDrawer score={makeScore()} offerTitle="Offer" onClose={vi.fn()} />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });
});
