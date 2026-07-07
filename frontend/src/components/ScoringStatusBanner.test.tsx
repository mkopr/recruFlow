import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { ScoringStatus } from '../api/scoring';
import { ScoringStatusBanner } from './ScoringStatusBanner';

function makeStatus(overrides: Partial<ScoringStatus> = {}): ScoringStatus {
  return {
    running: false,
    processed: 0,
    total: 0,
    remaining_backlog: 0,
    unscored_backlog: 0,
    started_at: null,
    finished_at: null,
    last_scored: 0,
    last_skipped: 0,
    last_failed: 0,
    ...overrides,
  };
}

describe('ScoringStatusBanner', () => {
  it('renders nothing before any scoring run has ever happened and nothing is unscored', () => {
    const { container } = render(<ScoringStatusBanner status={makeStatus()} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('shows the live unscored backlog even before any run has completed', () => {
    render(<ScoringStatusBanner status={makeStatus({ unscored_backlog: 17288 })} />);

    expect(screen.getByText(/17288 offers not yet scored/i)).toBeInTheDocument();
  });

  it('renders nothing when status is null', () => {
    const { container } = render(<ScoringStatusBanner status={null} />);

    expect(container).toBeEmptyDOMElement();
  });

  it('shows live progress while a run is in flight', () => {
    render(
      <ScoringStatusBanner
        status={makeStatus({
          running: true,
          processed: 3,
          total: 10,
          started_at: '2026-01-01T00:00:00Z',
        })}
      />,
    );

    expect(screen.getByText(/scoring offers/i)).toBeInTheDocument();
    expect(screen.getByText(/3\/10/)).toBeInTheDocument();
  });

  it('summarizes the last completed run and surfaces failures', () => {
    render(
      <ScoringStatusBanner
        status={makeStatus({
          finished_at: '2026-01-01T00:05:00Z',
          last_scored: 20,
          last_failed: 2,
          unscored_backlog: 14986,
        })}
      />,
    );

    expect(screen.getByText(/scored 20 offers/i)).toBeInTheDocument();
    expect(screen.getByText(/2 failed to score/i)).toBeInTheDocument();
    expect(screen.getByText(/14986 offers not yet scored/i)).toBeInTheDocument();
  });

  it('omits the backlog message once nothing remains unscored', () => {
    render(
      <ScoringStatusBanner
        status={makeStatus({ finished_at: '2026-01-01T00:05:00Z', last_scored: 1 })}
      />,
    );

    expect(screen.queryByText(/not yet scored/i)).not.toBeInTheDocument();
  });
});
