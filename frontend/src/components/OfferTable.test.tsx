import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { OfferSummary } from '../api/offers';
import { OfferTable } from './OfferTable';

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
    created_at: '2026-06-01T00:00:00Z',
    ...overrides,
  };
}

describe('OfferTable', () => {
  it('renders required columns with correct values', () => {
    render(<OfferTable offers={[makeOffer()]} loading={false} />);

    expect(screen.getByText('Senior Backend Engineer')).toBeInTheDocument();
    expect(screen.getByText('Acme')).toBeInTheDocument();
    expect(screen.getByText('justjoinit')).toBeInTheDocument();
    expect(screen.getByText('15,000-25,000 PLN')).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: 'Remote' })).toBeInTheDocument();
    expect(screen.getByText('senior')).toBeInTheDocument();
    expect(
      screen.getByText(new Date('2026-06-01T00:00:00Z').toLocaleDateString()),
    ).toBeInTheDocument();
  });

  it('shows an empty state when there are no offers', () => {
    render(<OfferTable offers={[]} loading={false} />);

    expect(screen.getByText(/no offers yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not show the empty state while loading with no offers yet', () => {
    render(<OfferTable offers={[]} loading={true} />);

    expect(screen.queryByText(/no offers yet/i)).not.toBeInTheDocument();
  });

  it('formats a min-only salary range with a plus sign', () => {
    render(
      <OfferTable offers={[makeOffer({ salary_min: 20000, salary_max: null })]} loading={false} />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('formats a max-only salary range with "up to"', () => {
    render(
      <OfferTable offers={[makeOffer({ salary_min: null, salary_max: 25000 })]} loading={false} />,
    );

    expect(screen.getByText('up to 25,000 PLN')).toBeInTheDocument();
  });

  it('defaults to PLN when currency is null but salary is present', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: 20000, salary_max: null, salary_currency: null })]}
        loading={false}
      />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('shows a dash when no salary information is present', () => {
    render(
      <OfferTable offers={[makeOffer({ salary_min: null, salary_max: null })]} loading={false} />,
    );

    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('sorts offers by posted date, newest first', () => {
    const older = makeOffer({ id: 1, title: 'Older', posted_at: '2026-01-01T00:00:00Z' });
    const newer = makeOffer({ id: 2, title: 'Newer', posted_at: '2026-06-01T00:00:00Z' });

    render(<OfferTable offers={[older, newer]} loading={false} />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Newer');
    expect(rows[1]).toHaveTextContent('Older');
  });
});
