import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as connectorsApi from '../api/connectors';
import { useKnownSources } from './useKnownSources';

vi.mock('../api/connectors', () => ({
  fetchConnectors: vi.fn(),
}));

const fetchConnectorsMock = vi.mocked(connectorsApi.fetchConnectors);

beforeEach(() => {
  fetchConnectorsMock.mockReset();
});

describe('useKnownSources', () => {
  it('calls fetchConnectors once on mount and exposes the resolved array', async () => {
    fetchConnectorsMock.mockResolvedValue([
      { id: 'justjoinit', label: 'JustJoin.it' },
      { id: 'solid_jobs', label: 'SOLID.Jobs' },
    ]);

    const { result } = renderHook(() => useKnownSources());

    await waitFor(() => expect(result.current.sources).toHaveLength(2));
    expect(fetchConnectorsMock).toHaveBeenCalledTimes(1);
  });

  it('leaves sources as an empty array rather than throwing when the fetch rejects', async () => {
    fetchConnectorsMock.mockRejectedValue(new Error('boom'));

    const { result } = renderHook(() => useKnownSources());

    await waitFor(() => expect(fetchConnectorsMock).toHaveBeenCalledTimes(1));
    expect(result.current.sources).toEqual([]);
  });
});
