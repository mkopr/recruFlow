import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offerScoreApi from '../api/offerScore';
import { useOfferScoreDetail } from './useOfferScoreDetail';

vi.mock('../api/offerScore', () => ({
  fetchOfferScore: vi.fn(),
}));

const fetchOfferScoreMock = vi.mocked(offerScoreApi.fetchOfferScore);

function makeScore(overrides: Partial<offerScoreApi.MatchScoreResponse> = {}) {
  return {
    id: 1,
    offer_id: 1,
    profile_id: 1,
    engine: 'langchain',
    grade: 'A',
    dimensions: { skill_match: 0.9 },
    rationale: 'Great fit',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  fetchOfferScoreMock.mockReset();
});

describe('useOfferScoreDetail', () => {
  it('does not fetch when offerId is null', () => {
    const { result } = renderHook(() => useOfferScoreDetail(null));

    expect(result.current.score).toBeNull();
    expect(result.current.loading).toBe(false);
    expect(fetchOfferScoreMock).not.toHaveBeenCalled();
  });

  it('fetches the score for the given offer id', async () => {
    const score = makeScore();
    fetchOfferScoreMock.mockResolvedValue(score);

    const { result } = renderHook(() => useOfferScoreDetail(1));

    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.score).toEqual(score);
    expect(fetchOfferScoreMock).toHaveBeenCalledWith(1);
  });

  it('refetches when the offer id changes', async () => {
    fetchOfferScoreMock.mockImplementation((id: number) =>
      Promise.resolve(makeScore({ offer_id: id, grade: id === 1 ? 'A' : 'B' })),
    );

    const { result, rerender } = renderHook((id: number | null) => useOfferScoreDetail(id), {
      initialProps: 1,
    });

    await waitFor(() => expect(result.current.score?.grade).toBe('A'));

    rerender(2);

    await waitFor(() => expect(result.current.score?.grade).toBe('B'));
    expect(fetchOfferScoreMock).toHaveBeenCalledTimes(2);
  });

  it('degrades to a null score without throwing when the fetch rejects', async () => {
    fetchOfferScoreMock.mockRejectedValue(new Error('failed'));

    const { result } = renderHook(() => useOfferScoreDetail(1));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.score).toBeNull();
  });
});
