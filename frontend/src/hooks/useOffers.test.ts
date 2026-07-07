import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offersApi from '../api/offers';
import type { OfferListFilters, OfferListPage } from '../api/offers';
import { useOffers } from './useOffers';

vi.mock('../api/offers', () => ({
  fetchOffers: vi.fn(),
}));

const fetchOffersMock = vi.mocked(offersApi.fetchOffers);

const PAGE: OfferListPage = { limit: 50, offset: 0 };

beforeEach(() => {
  fetchOffersMock.mockReset();
  fetchOffersMock.mockResolvedValue({ items: [], total: 0 });
});

describe('useOffers', () => {
  it('fetches immediately on mount, with no debounce delay', async () => {
    const { result } = renderHook(() => useOffers({}, PAGE));

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(fetchOffersMock).toHaveBeenCalledTimes(1);
  });

  it('exposes the total count returned by the API for pagination', async () => {
    fetchOffersMock.mockResolvedValue({ items: [], total: 137 });

    const { result } = renderHook(() => useOffers({}, PAGE));

    await waitFor(() => expect(result.current.total).toBe(137));
  });

  it('debounces rapid filter changes into a single fetch (BUG17)', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook(
        (filters: OfferListFilters) => useOffers(filters, PAGE),
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
          minGrade: undefined,
        },
        PAGE,
      );
    } finally {
      vi.useRealTimers();
    }
  });

  it('refetches with the new limit/offset when the page changes', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { result, rerender } = renderHook((page: OfferListPage) => useOffers({}, page), {
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
          minGrade: undefined,
        },
        { limit: 50, offset: 50 },
      );
    } finally {
      vi.useRealTimers();
    }
  });
});
