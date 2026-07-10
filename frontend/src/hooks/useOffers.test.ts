import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offersApi from '../api/offers';
import type { OfferListFilters, OfferListPage, OfferListSort, OfferSummary } from '../api/offers';
import { useOffers } from './useOffers';

vi.mock('../api/offers', () => ({
  fetchOffers: vi.fn(),
}));

const fetchOffersMock = vi.mocked(offersApi.fetchOffers);

const PAGE: OfferListPage = { limit: 50, offset: 0 };
const SORT: OfferListSort = { orderBy: 'posted_at', order: 'desc' };

function makeOffer(overrides: Partial<OfferSummary> = {}): OfferSummary {
  return {
    id: 1,
    source: 'justjoinit',
    external_id: 'ext-1',
    canonical_url: 'https://example.com/jobs/1',
    title: 'Senior Backend Engineer',
    company: 'Acme',
    location: 'Warsaw',
    remote: true,
    seniority: 'senior',
    salary_min: 15000,
    salary_max: 25000,
    salary_currency: 'PLN',
    contract_type: 'B2B',
    posted_at: '2026-06-01T00:00:00Z',
    industry_tags: [],
    created_at: '2026-06-01T00:00:00Z',
    applied: false,
    hide: false,
    notes: null,
    link_opened_at: null,
    score_percent: null,
    ...overrides,
  };
}

beforeEach(() => {
  fetchOffersMock.mockReset();
  fetchOffersMock.mockResolvedValue({ items: [], total: 0 });
});

describe('useOffers', () => {
  it('fetches immediately on mount, with no debounce delay', async () => {
    const { result } = renderHook(() => useOffers({}, SORT, PAGE));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchOffersMock).toHaveBeenCalledTimes(1);
  });

  it('exposes the total count returned by the API for pagination', async () => {
    fetchOffersMock.mockResolvedValue({ items: [], total: 137 });

    const { result } = renderHook(() => useOffers({}, SORT, PAGE));

    await waitFor(() => expect(result.current.total).toBe(137));
  });

  it('debounces rapid filter changes into a single fetch (BUG17)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook(
        (filters: OfferListFilters) => useOffers(filters, SORT, PAGE),
        {
          initialProps: {} as OfferListFilters,
        },
      );

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      rerender({ minSalary: 1 });
      rerender({ minSalary: 15 });
      rerender({ minSalary: 150 });

      await vi.advanceTimersByTimeAsync(100);
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      await vi.advanceTimersByTimeAsync(300);
      expect(fetchOffersMock).toHaveBeenCalledTimes(2);
      expect(fetchOffersMock).toHaveBeenLastCalledWith(
        {
          source: undefined,
          remote: undefined,
          seniority: undefined,
          minSalary: 150,
          minScore: undefined,
        },
        SORT,
        PAGE,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('refetches with the new limit/offset when the page changes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook((page: OfferListPage) => useOffers({}, SORT, page), {
        initialProps: PAGE,
      });

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      rerender({ limit: 50, offset: 50 });

      await vi.advanceTimersByTimeAsync(300);
      expect(fetchOffersMock).toHaveBeenCalledTimes(2);
      expect(fetchOffersMock).toHaveBeenLastCalledWith(
        {
          source: undefined,
          remote: undefined,
          seniority: undefined,
          minSalary: undefined,
          minScore: undefined,
        },
        SORT,
        { limit: 50, offset: 50 },
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('refetches with the new sort when the sort changes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook((sort: OfferListSort) => useOffers({}, sort, PAGE), {
        initialProps: SORT,
      });

      await waitFor(() => expect(result.current.loading).toBe(false));
      expect(fetchOffersMock).toHaveBeenCalledTimes(1);

      const scoreSort: OfferListSort = { orderBy: 'score_percent', order: 'asc' };
      rerender(scoreSort);

      await vi.advanceTimersByTimeAsync(300);
      expect(fetchOffersMock).toHaveBeenCalledTimes(2);
      expect(fetchOffersMock).toHaveBeenLastCalledWith(
        {
          source: undefined,
          remote: undefined,
          seniority: undefined,
          minSalary: undefined,
          minScore: undefined,
        },
        scoreSort,
        PAGE,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('threads showApplied and showHidden through to fetchOffers', async () => {
    const { result } = renderHook(() =>
      useOffers({ showApplied: true, showHidden: true }, SORT, PAGE),
    );

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchOffersMock).toHaveBeenLastCalledWith(
      {
        source: undefined,
        remote: undefined,
        seniority: undefined,
        minSalary: undefined,
        minScore: undefined,
        showApplied: true,
        showHidden: true,
      },
      SORT,
      PAGE,
    );
  });

  it('replaces the matching offer in state', async () => {
    const offer = makeOffer({ id: 1, applied: false });
    fetchOffersMock.mockResolvedValue({ items: [offer], total: 1 });

    const { result } = renderHook(() => useOffers({}, SORT, PAGE));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const patched = { ...offer, applied: true };
    act(() => {
      result.current.updateOffer(patched);
    });

    expect(result.current.offers).toEqual([patched]);
  });

  it('removes an offer from state when hidden while showHidden is false', async () => {
    const offer = makeOffer({ id: 1, hide: false });
    fetchOffersMock.mockResolvedValue({ items: [offer], total: 1 });

    const { result } = renderHook(() => useOffers({ showHidden: false }, SORT, PAGE));
    await waitFor(() => expect(result.current.loading).toBe(false));

    act(() => {
      result.current.updateOffer({ ...offer, hide: true });
    });

    expect(result.current.offers).toEqual([]);
  });

  it('keeps a hidden offer in state when showHidden is true', async () => {
    const offer = makeOffer({ id: 1, hide: false });
    fetchOffersMock.mockResolvedValue({ items: [offer], total: 1 });

    const { result } = renderHook(() => useOffers({ showHidden: true }, SORT, PAGE));
    await waitFor(() => expect(result.current.loading).toBe(false));

    const patched = { ...offer, hide: true };
    act(() => {
      result.current.updateOffer(patched);
    });

    expect(result.current.offers).toEqual([patched]);
  });
});
