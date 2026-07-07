import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as scoringApi from '../api/scoring';
import { useScoringStatus } from './useScoringStatus';

vi.mock('../api/scoring', () => ({
  fetchScoringStatus: vi.fn(),
}));

const fetchScoringStatusMock = vi.mocked(scoringApi.fetchScoringStatus);

function makeStatus(overrides: Partial<scoringApi.ScoringStatus> = {}): scoringApi.ScoringStatus {
  return {
    running: false,
    processed: 0,
    total: 0,
    remaining_backlog: 0,
    started_at: null,
    finished_at: null,
    last_scored: 0,
    last_skipped: 0,
    last_failed: 0,
    ...overrides,
  };
}

beforeEach(() => {
  fetchScoringStatusMock.mockReset();
});

describe('useScoringStatus', () => {
  it('polls once on mount and exposes the result', async () => {
    fetchScoringStatusMock.mockResolvedValue(makeStatus({ running: true, processed: 2, total: 5 }));

    const { result } = renderHook(() => useScoringStatus());

    await waitFor(() => expect(result.current.status?.running).toBe(true));
    expect(result.current.status?.processed).toBe(2);
    expect(result.current.status?.total).toBe(5);
  });

  it('keeps the previous status instead of clearing it when a later poll fails', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      fetchScoringStatusMock.mockResolvedValueOnce(makeStatus({ last_scored: 3 }));
      fetchScoringStatusMock.mockRejectedValueOnce(new Error('network error'));

      const { result } = renderHook(() => useScoringStatus());

      await waitFor(() => expect(result.current.status?.last_scored).toBe(3));

      await vi.advanceTimersByTimeAsync(5000);

      expect(fetchScoringStatusMock).toHaveBeenCalledTimes(2);
      expect(result.current.status?.last_scored).toBe(3);
    } finally {
      vi.useRealTimers();
    }
  });
});
