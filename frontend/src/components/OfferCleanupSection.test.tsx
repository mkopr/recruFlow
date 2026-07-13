import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as useOfferCleanupModule from '../hooks/useOfferCleanup';
import { OfferCleanupSection } from './OfferCleanupSection';

vi.mock('../hooks/useOfferCleanup', () => ({
  useOfferCleanup: vi.fn(),
}));

const useOfferCleanupMock = vi.mocked(useOfferCleanupModule.useOfferCleanup);

function baseResult(
  overrides: Partial<ReturnType<typeof useOfferCleanupModule.useOfferCleanup>> = {},
): ReturnType<typeof useOfferCleanupModule.useOfferCleanup> {
  return {
    previewing: false,
    deleting: false,
    error: null,
    preview: null,
    result: null,
    loadPreview: vi.fn(),
    confirmDelete: vi.fn(),
    cancelPreview: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  useOfferCleanupMock.mockReset();
});

describe('OfferCleanupSection', () => {
  it('the delete button is disabled with no date chosen', () => {
    useOfferCleanupMock.mockReturnValue(baseResult());

    render(<OfferCleanupSection />);

    expect(screen.getByRole('button', { name: /Delete offers older than/ })).toBeDisabled();
  });

  it('the delete button is enabled once a date is picked', () => {
    useOfferCleanupMock.mockReturnValue(baseResult());

    render(<OfferCleanupSection />);
    const input = screen.getByLabelText('Delete offers posted before');
    fireEvent.change(input, { target: { value: '2026-01-01' } });

    expect(screen.getByRole('button', { name: /Delete offers older than/ })).toBeEnabled();
  });

  it('clicking the button calls loadPreview and opens the confirmation dialog with the returned counts', async () => {
    const loadPreview = vi.fn();
    useOfferCleanupMock.mockReturnValue(baseResult({ loadPreview }));

    render(<OfferCleanupSection />);
    const input = screen.getByLabelText('Delete offers posted before');
    fireEvent.change(input, { target: { value: '2026-01-01' } });
    await userEvent.click(screen.getByRole('button', { name: /Delete offers older than/ }));

    expect(loadPreview).toHaveBeenCalledWith('2026-01-01T00:00:00.000Z');

    useOfferCleanupMock.mockReturnValue(
      baseResult({ loadPreview, preview: { wouldDelete: 4, wouldSkip: 2 } }),
    );
    render(<OfferCleanupSection />);

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText(/This will delete 4 offer\(s\)/)).toBeInTheDocument();
    expect(screen.getByText(/2 offer\(s\) will be skipped/)).toBeInTheDocument();
  });

  it('clicking Cancel closes the dialog without calling delete', async () => {
    const cancelPreview = vi.fn();
    const confirmDelete = vi.fn();
    useOfferCleanupMock.mockReturnValue(
      baseResult({
        preview: { wouldDelete: 1, wouldSkip: 0 },
        cancelPreview,
        confirmDelete,
      }),
    );

    render(<OfferCleanupSection />);
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));

    expect(cancelPreview).toHaveBeenCalled();
    expect(confirmDelete).not.toHaveBeenCalled();
  });

  it('clicking Confirm calls confirmDelete; the result message shows deleted+skipped counts', async () => {
    const confirmDelete = vi.fn();
    useOfferCleanupMock.mockReturnValue(
      baseResult({
        preview: { wouldDelete: 1, wouldSkip: 0 },
        confirmDelete,
      }),
    );

    render(<OfferCleanupSection />);
    fireEvent.change(screen.getByLabelText('Delete offers posted before'), {
      target: { value: '2026-01-01' },
    });
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    expect(confirmDelete).toHaveBeenCalledWith('2026-01-01T00:00:00.000Z');

    useOfferCleanupMock.mockReturnValue(baseResult({ result: { deleted: 5, skipped: 1 } }));
    render(<OfferCleanupSection />);

    expect(screen.getByText('Deleted 5 offer(s), skipped 1 in your pipeline.')).toBeInTheDocument();
  });
});
