import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';

import type { OfferSummary } from '../api/offers';
import type { MatchScoreResponse } from '../api/offerScore';
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
    industry_tags: [],
    created_at: '2026-06-01T00:00:00Z',
    ...overrides,
  };
}

function makeScore(overrides: Partial<MatchScoreResponse> = {}): MatchScoreResponse {
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

describe('OfferTable', () => {
  it('renders required columns with correct values', () => {
    render(<OfferTable offers={[makeOffer()]} loading={false} scores={{}} minGrade="" />);

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
    render(<OfferTable offers={[]} loading={false} scores={{}} minGrade="" />);

    expect(screen.getByText(/no offers yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not show the empty state while loading with no offers yet', () => {
    render(<OfferTable offers={[]} loading={true} scores={{}} minGrade="" />);

    expect(screen.queryByText(/no offers yet/i)).not.toBeInTheDocument();
  });

  it('formats a min-only salary range with a plus sign', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: 20000, salary_max: null })]}
        loading={false}
        scores={{}}
        minGrade=""
      />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('formats a max-only salary range with "up to"', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: null, salary_max: 25000 })]}
        loading={false}
        scores={{}}
        minGrade=""
      />,
    );

    expect(screen.getByText('up to 25,000 PLN')).toBeInTheDocument();
  });

  it('defaults to PLN when currency is null but salary is present', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: 20000, salary_max: null, salary_currency: null })]}
        loading={false}
        scores={{}}
        minGrade=""
      />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('shows a dash when no salary information is present', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: null, salary_max: null })]}
        loading={false}
        scores={{}}
        minGrade=""
      />,
    );

    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('sorts offers by posted date, newest first', () => {
    const older = makeOffer({ id: 1, title: 'Older', posted_at: '2026-01-01T00:00:00Z' });
    const newer = makeOffer({ id: 2, title: 'Newer', posted_at: '2026-06-01T00:00:00Z' });

    render(<OfferTable offers={[older, newer]} loading={false} scores={{}} minGrade="" />);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Newer');
    expect(rows[1]).toHaveTextContent('Older');
  });

  it('renders a grade badge for an offer with a MatchScore', () => {
    const offer = makeOffer({ id: 1 });
    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        scores={{ 1: makeScore({ grade: 'A' }) }}
        minGrade=""
      />,
    );

    expect(screen.getByText('A')).toBeInTheDocument();
  });

  it('renders the not-yet-scored badge for an offer with no score entry', () => {
    const offer = makeOffer({ id: 1 });
    render(<OfferTable offers={[offer]} loading={false} scores={{}} minGrade="" />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
  });

  it("opens the drawer with that offer's breakdown when its badge is clicked", async () => {
    const offer = makeOffer({ id: 1 });
    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        scores={{ 1: makeScore({ grade: 'A', rationale: 'Strong fit' }) }}
        minGrade=""
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /grade a/i }));

    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(screen.getByText('Strong fit')).toBeInTheDocument();
  });

  it('does not open a drawer when clicking the not-yet-scored badge', async () => {
    const offer = makeOffer({ id: 1 });
    render(<OfferTable offers={[offer]} loading={false} scores={{}} minGrade="" />);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/not yet scored/i));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('sorts by grade ascending on the first header click, then descending on the second click', async () => {
    const offerC = makeOffer({ id: 1, title: 'OfferC', posted_at: '2026-01-01T00:00:00Z' });
    const offerA = makeOffer({ id: 2, title: 'OfferA', posted_at: '2026-02-01T00:00:00Z' });
    const offerF = makeOffer({ id: 3, title: 'OfferF', posted_at: '2026-03-01T00:00:00Z' });

    render(
      <OfferTable
        offers={[offerC, offerA, offerF]}
        loading={false}
        scores={{
          1: makeScore({ offer_id: 1, grade: 'C' }),
          2: makeScore({ offer_id: 2, grade: 'A' }),
          3: makeScore({ offer_id: 3, grade: 'F' }),
        }}
        minGrade=""
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Grade' }));
    let rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('OfferA');
    expect(rows[1]).toHaveTextContent('OfferC');
    expect(rows[2]).toHaveTextContent('OfferF');

    await userEvent.click(screen.getByRole('button', { name: 'Grade' }));
    rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('OfferF');
    expect(rows[1]).toHaveTextContent('OfferC');
    expect(rows[2]).toHaveTextContent('OfferA');
  });

  it('keeps unscored offers last regardless of grade sort direction', async () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored' });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored' });

    render(
      <OfferTable
        offers={[scoredOffer, unscoredOffer]}
        loading={false}
        scores={{ 1: makeScore({ offer_id: 1, grade: 'B' }) }}
        minGrade=""
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Grade' }));
    let rows = screen.getAllByRole('row').slice(1);
    expect(rows[rows.length - 1]).toHaveTextContent('Unscored');

    await userEvent.click(screen.getByRole('button', { name: 'Grade' }));
    rows = screen.getAllByRole('row').slice(1);
    expect(rows[rows.length - 1]).toHaveTextContent('Unscored');
  });

  it('hides offers below the minimum grade filter', () => {
    const offerA = makeOffer({ id: 1, title: 'OfferA' });
    const offerD = makeOffer({ id: 2, title: 'OfferD' });

    render(
      <OfferTable
        offers={[offerA, offerD]}
        loading={false}
        scores={{
          1: makeScore({ offer_id: 1, grade: 'A' }),
          2: makeScore({ offer_id: 2, grade: 'D' }),
        }}
        minGrade="B"
      />,
    );

    expect(screen.getByText('OfferA')).toBeInTheDocument();
    expect(screen.queryByText('OfferD')).not.toBeInTheDocument();
  });

  it('hides not-yet-scored offers when a minimum grade filter is active', () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored' });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored' });

    render(
      <OfferTable
        offers={[scoredOffer, unscoredOffer]}
        loading={false}
        scores={{ 1: makeScore({ offer_id: 1, grade: 'B' }) }}
        minGrade="B"
      />,
    );

    expect(screen.getByText('Scored')).toBeInTheDocument();
    expect(screen.queryByText('Unscored')).not.toBeInTheDocument();
  });

  it('shows a distinct empty state when the grade filter hides every offer, naming the unscored count', () => {
    const unscoredOfferA = makeOffer({ id: 1, title: 'OfferA' });
    const unscoredOfferB = makeOffer({ id: 2, title: 'OfferB' });

    render(
      <OfferTable
        offers={[unscoredOfferA, unscoredOfferB]}
        loading={false}
        scores={{}}
        minGrade="F"
      />,
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByText(/no offers meet the minimum grade filter/i)).toBeInTheDocument();
    expect(screen.getByText(/2 of 2 loaded offers haven't been scored yet/i)).toBeInTheDocument();
  });

  it('shows unscored offers when no minimum grade filter is active', () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored' });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored' });

    render(
      <OfferTable
        offers={[scoredOffer, unscoredOffer]}
        loading={false}
        scores={{ 1: makeScore({ offer_id: 1, grade: 'B' }) }}
        minGrade=""
      />,
    );

    expect(screen.getByText('Scored')).toBeInTheDocument();
    expect(screen.getByText('Unscored')).toBeInTheDocument();
  });
});
