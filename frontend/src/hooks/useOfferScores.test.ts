import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offerScoreApi from '../api/offerScore';
import { useOfferScores } from './useOfferScores';

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

describe('useOfferScores', () => {
  it('fetches and returns a score keyed by offer id', async () => {
    const score = makeScore();
    fetchOfferScoreMock.mockResolvedValue(score);

    const { result } = renderHook(() => useOfferScores([1]));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.scores[1]).toEqual(score);
  });

  it('returns null for an offer with no score yet, not an error', async () => {
    fetchOfferScoreMock.mockResolvedValue(null);

    const { result } = renderHook(() => useOfferScores([1]));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.scores[1]).toBeNull();
  });

  it("one offer's rejected fetch degrades to null without discarding the other offers' resolved scores", async () => {
    const score = makeScore({ offer_id: 1 });
    fetchOfferScoreMock.mockImplementation((id: number) =>
      id === 1 ? Promise.resolve(score) : Promise.reject(new Error('failed')),
    );

    const { result } = renderHook(() => useOfferScores([1, 2]));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.scores[1]).toEqual(score);
    expect(result.current.scores[2]).toBeNull();
  });

  it('loading starts true and becomes false once every fetch settles', async () => {
    let resolveFetch: (value: offerScoreApi.MatchScoreResponse | null) => void = () => {};
    fetchOfferScoreMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );

    const { result } = renderHook(() => useOfferScores([1]));

    expect(result.current.loading).toBe(true);

    resolveFetch(makeScore());
    await waitFor(() => expect(result.current.loading).toBe(false));
  });

  it('yields an empty scores map without calling fetchOfferScore for an empty offerIds array', async () => {
    const { result } = renderHook(() => useOfferScores([]));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.scores).toEqual({});
    expect(fetchOfferScoreMock).not.toHaveBeenCalled();
  });

  it('refetch re-pulls scores for the same offer ids (BUG16: a score can complete after the initial load)', async () => {
    fetchOfferScoreMock.mockResolvedValue(null);

    const { result } = renderHook(() => useOfferScores([1]));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.scores[1]).toBeNull();

    const score = makeScore();
    fetchOfferScoreMock.mockResolvedValue(score);
    result.current.refetch();

    await waitFor(() => expect(result.current.scores[1]).toEqual(score));
  });

  it('only fetches ids not already cached when the offer id list changes (BUG17)', async () => {
    fetchOfferScoreMock.mockImplementation((id: number) =>
      Promise.resolve(makeScore({ offer_id: id, grade: id === 1 ? 'A' : 'B' })),
    );

    const { result, rerender } = renderHook((ids: number[]) => useOfferScores(ids), {
      initialProps: [1],
    });

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchOfferScoreMock).toHaveBeenCalledTimes(1);
    expect(fetchOfferScoreMock).toHaveBeenCalledWith(1);

    // A new array reference containing the same id 1 plus a brand-new id 2 —
    // only id 2 should trigger a network call.
    rerender([1, 2]);

    await waitFor(() => expect(result.current.scores[2]).not.toBeUndefined());
    expect(fetchOfferScoreMock).toHaveBeenCalledTimes(2);
    expect(fetchOfferScoreMock).toHaveBeenCalledWith(2);
    expect(result.current.scores[1]?.grade).toBe('A');
    expect(result.current.scores[2]?.grade).toBe('B');
  });
});
