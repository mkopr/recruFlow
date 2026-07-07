import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as scoringApi from '../api/scoring';
import { ScoreNowButton } from './ScoreNowButton';

vi.mock('../api/scoring', () => ({
  triggerBatchScoring: vi.fn(),
}));

const triggerBatchScoringMock = vi.mocked(scoringApi.triggerBatchScoring);

function idleStatus(unscoredBacklog: number): scoringApi.ScoringStatus {
  return {
    running: false,
    processed: 0,
    total: 0,
    remaining_backlog: 0,
    unscored_backlog: unscoredBacklog,
    started_at: null,
    finished_at: null,
    last_scored: 0,
    last_skipped: 0,
    last_failed: 0,
  };
}

beforeEach(() => {
  triggerBatchScoringMock.mockReset();
});

describe('ScoreNowButton', () => {
  it('shows the pending backlog count when idle with unscored offers', () => {
    render(<ScoreNowButton status={idleStatus(7)} onScored={vi.fn()} />);

    expect(screen.getByText('7 offers pending')).toBeInTheDocument();
  });

  it('shows "All offers scored" when idle with no backlog', () => {
    render(<ScoreNowButton status={idleStatus(0)} onScored={vi.fn()} />);

    expect(screen.getByText('All offers scored')).toBeInTheDocument();
  });

  it('shows a loading state while scoring is in progress', async () => {
    let resolveScoring: (value: scoringApi.BatchScoringResponse) => void = () => {};
    triggerBatchScoringMock.mockReturnValue(
      new Promise((resolve) => {
        resolveScoring = resolve;
      }),
    );
    const onScored = vi.fn();

    render(<ScoreNowButton status={idleStatus(3)} onScored={onScored} />);
    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByText('Scoring…')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();

    resolveScoring({ scored: 5, skipped: 1, failed: 0, remaining: 3 });
    await waitFor(() => expect(screen.getByRole('button')).not.toBeDisabled());
  });

  it('calls onScored and shows a result summary on success', async () => {
    triggerBatchScoringMock.mockResolvedValue({ scored: 5, skipped: 1, failed: 0, remaining: 3 });
    const onScored = vi.fn();

    render(<ScoreNowButton status={idleStatus(8)} onScored={onScored} />);
    await userEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(onScored).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Scored 5, 0 failed, 3 remaining')).toBeInTheDocument();
  });

  it('shows an inline error and does not call onScored on failure', async () => {
    triggerBatchScoringMock.mockRejectedValue(new Error('failed to trigger scoring'));
    const onScored = vi.fn();

    render(<ScoreNowButton status={idleStatus(3)} onScored={onScored} />);
    await userEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(screen.getByText('failed to trigger scoring')).toBeInTheDocument());
    expect(onScored).not.toHaveBeenCalled();
  });

  it('is disabled and does not trigger scoring while a scoring run is already active', async () => {
    const onScored = vi.fn();
    const status: scoringApi.ScoringStatus = { ...idleStatus(3), running: true };

    render(<ScoreNowButton status={status} onScored={onScored} />);
    expect(screen.getByRole('button')).toBeDisabled();

    await userEvent.click(screen.getByRole('button'));
    expect(triggerBatchScoringMock).not.toHaveBeenCalled();
  });

  it('ignores a second click while a scoring request is already in flight', async () => {
    triggerBatchScoringMock.mockReturnValue(new Promise(() => {}));
    const onScored = vi.fn();

    render(<ScoreNowButton status={idleStatus(3)} onScored={onScored} />);
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('button'));

    expect(triggerBatchScoringMock).toHaveBeenCalledTimes(1);
  });
});
