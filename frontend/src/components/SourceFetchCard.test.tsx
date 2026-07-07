import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offersApi from '../api/offers';
import { SourceFetchCard } from './SourceFetchCard';

vi.mock('../api/offers', () => ({
  triggerIngest: vi.fn(),
}));

const triggerIngestMock = vi.mocked(offersApi.triggerIngest);

beforeEach(() => {
  triggerIngestMock.mockReset();
});

describe('SourceFetchCard', () => {
  it('shows "Never fetched" when there is no last-fetched timestamp', () => {
    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={vi.fn()}
      />,
    );

    expect(screen.getByText('Never fetched')).toBeInTheDocument();
  });

  it('shows a formatted last-fetched timestamp', () => {
    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt="2026-07-06T12:00:00Z"
        onIngested={vi.fn()}
      />,
    );

    expect(screen.getByText(new Date('2026-07-06T12:00:00Z').toLocaleString())).toBeInTheDocument();
  });

  it('shows a loading state while the fetch is in progress', async () => {
    let resolveFetch: (value: offersApi.IngestResponse) => void = () => {};
    triggerIngestMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      }),
    );
    const onIngested = vi.fn();

    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={onIngested}
      />,
    );
    await userEvent.click(screen.getByRole('button'));

    expect(screen.getByText('Fetching…')).toBeInTheDocument();
    expect(screen.getByRole('button')).toBeDisabled();

    resolveFetch({ source: 'justjoinit', ok: true, fetched: 10, created: 4 });
    await waitFor(() => expect(screen.getByRole('button')).not.toBeDisabled());
  });

  it('calls onIngested and shows a result summary on success', async () => {
    triggerIngestMock.mockResolvedValue({
      source: 'justjoinit',
      ok: true,
      fetched: 10,
      created: 4,
    });
    const onIngested = vi.fn();

    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={onIngested}
      />,
    );
    await userEvent.click(screen.getByRole('button'));

    await waitFor(() => expect(onIngested).toHaveBeenCalledTimes(1));
    expect(screen.getByText('Fetched 10, 4 new')).toBeInTheDocument();
  });

  it('shows an inline error and does not call onIngested on failure', async () => {
    triggerIngestMock.mockRejectedValue(new Error('failed to trigger ingest for justjoinit'));
    const onIngested = vi.fn();

    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={onIngested}
      />,
    );
    await userEvent.click(screen.getByRole('button'));

    await waitFor(() =>
      expect(screen.getByText('failed to trigger ingest for justjoinit')).toBeInTheDocument(),
    );
    expect(onIngested).not.toHaveBeenCalled();
  });

  it('shows the error message and does not call onIngested when the ingest reports ok: false', async () => {
    triggerIngestMock.mockResolvedValue({
      source: 'justjoinit',
      ok: false,
      fetched: 0,
      created: 0,
      error_message: 'failed to fetch JustJoin.it offers',
    });
    const onIngested = vi.fn();

    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={onIngested}
      />,
    );
    await userEvent.click(screen.getByRole('button'));

    await waitFor(() =>
      expect(screen.getByText('failed to fetch JustJoin.it offers')).toBeInTheDocument(),
    );
    expect(onIngested).not.toHaveBeenCalled();
  });

  it('ignores a second click while a fetch is already in progress', async () => {
    triggerIngestMock.mockReturnValue(new Promise(() => {}));
    const onIngested = vi.fn();

    render(
      <SourceFetchCard
        source="justjoinit"
        label="JustJoin.it"
        lastFetchedAt={null}
        onIngested={onIngested}
      />,
    );
    await userEvent.click(screen.getByRole('button'));
    await userEvent.click(screen.getByRole('button'));

    expect(triggerIngestMock).toHaveBeenCalledTimes(1);
  });
});
