import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import type { OfferListFilters } from '../api/offers';
import * as useKnownSourcesModule from '../hooks/useKnownSources';
import { OfferFilters } from './OfferFilters';

vi.mock('../hooks/useKnownSources', () => ({
  useKnownSources: vi.fn(),
}));

vi.mocked(useKnownSourcesModule.useKnownSources).mockReturnValue({
  sources: [
    {
      id: 'solid_jobs',
      label: 'SOLID.Jobs',
      offer_count: 0,
      scored_count: 0,
      unscored_count: 0,
      supports_fetch_scope: false,
    },
    {
      id: 'justjoinit',
      label: 'JustJoin.it',
      offer_count: 0,
      scored_count: 0,
      unscored_count: 0,
      supports_fetch_scope: false,
    },
    {
      id: 'nofluffjobs',
      label: 'NoFluffJobs',
      offer_count: 0,
      scored_count: 0,
      unscored_count: 0,
      supports_fetch_scope: false,
    },
  ],
  refetch: vi.fn(),
});

function renderFilters(filters: OfferListFilters, onChange: (next: OfferListFilters) => void) {
  return render(<OfferFilters filters={filters} onChange={onChange} />);
}

describe('OfferFilters', () => {
  it('calls onChange with the selected source', async () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    await userEvent.selectOptions(screen.getByLabelText('Source'), 'justjoinit');

    expect(onChange).toHaveBeenCalledWith({ source: 'justjoinit' });
  });

  it('calls onChange with a boolean when remote is selected', async () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    await userEvent.selectOptions(screen.getByLabelText('Remote'), 'true');

    expect(onChange).toHaveBeenCalledWith({ remote: true });
  });

  it('calls onChange with the selected seniority', async () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    await userEvent.selectOptions(screen.getByLabelText('Seniority'), 'senior');

    expect(onChange).toHaveBeenCalledWith({ seniority: 'senior' });
  });

  it('calls onChange with a parsed number for min salary', () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    fireEvent.change(screen.getByLabelText('Min salary (PLN)'), { target: { value: '15000' } });

    expect(onChange).toHaveBeenLastCalledWith({ minSalary: 15000 });
  });

  it('clamps negative min salary input to zero', () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    fireEvent.change(screen.getByLabelText('Min salary (PLN)'), { target: { value: '-5' } });

    expect(onChange).toHaveBeenLastCalledWith({ minSalary: 0 });
  });

  it('calls onChange with showApplied when the checkbox is toggled', async () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    await userEvent.click(screen.getByLabelText('Show applied offers'));

    expect(onChange).toHaveBeenCalledWith({ showApplied: true });
  });

  it('calls onChange with showHidden when the checkbox is toggled', async () => {
    const onChange = vi.fn();
    renderFilters({}, onChange);

    await userEvent.click(screen.getByLabelText('Show hidden offers'));

    expect(onChange).toHaveBeenCalledWith({ showHidden: true });
  });
});
