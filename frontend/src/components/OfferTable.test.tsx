import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offerScoreApi from '../api/offerScore';
import * as offersApi from '../api/offers';
import type { OfferSummary } from '../api/offers';
import { OfferTable } from './OfferTable';

vi.mock('../api/offerScore', () => ({
  fetchOfferScore: vi.fn(),
}));

vi.mock('../api/offers', () => ({
  patchOffer: vi.fn(),
}));

const fetchOfferScoreMock = vi.mocked(offerScoreApi.fetchOfferScore);
const patchOfferMock = vi.mocked(offersApi.patchOffer);
const onOfferPatchedMock = vi.fn();

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
    score_percent: null,
    ...overrides,
  };
}

function makeScore(
  overrides: Partial<offerScoreApi.MatchScoreResponse> = {},
): offerScoreApi.MatchScoreResponse {
  return {
    id: 1,
    offer_id: 1,
    profile_id: 1,
    engine: 'langchain',
    score_percent: 92,
    dimensions: { skill_match: 0.9 },
    rationale: 'Great fit',
    created_at: '2026-01-01T00:00:00Z',
    ...overrides,
  };
}

beforeEach(() => {
  fetchOfferScoreMock.mockReset();
  patchOfferMock.mockReset();
  onOfferPatchedMock.mockReset();
});

describe('OfferTable', () => {
  it('renders required columns with correct values', () => {
    render(
      <OfferTable
        offers={[makeOffer()]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

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
    render(
      <OfferTable offers={[]} loading={false} minScore="" onOfferPatched={onOfferPatchedMock} />,
    );

    expect(screen.getByText(/no offers yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not show the empty state while loading with no offers yet', () => {
    render(
      <OfferTable offers={[]} loading={true} minScore="" onOfferPatched={onOfferPatchedMock} />,
    );

    expect(screen.queryByText(/no offers yet/i)).not.toBeInTheDocument();
  });

  it('shows a distinct empty state naming the active minimum score filter', () => {
    render(
      <OfferTable offers={[]} loading={false} minScore={50} onOfferPatched={onOfferPatchedMock} />,
    );

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(
      screen.getByText(/no offers meet the minimum score filter \(50%\)/i),
    ).toBeInTheDocument();
  });

  it('formats a min-only salary range with a plus sign', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: 20000, salary_max: null })]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('formats a max-only salary range with "up to"', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: null, salary_max: 25000 })]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('up to 25,000 PLN')).toBeInTheDocument();
  });

  it('defaults to PLN when currency is null but salary is present', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: 20000, salary_max: null, salary_currency: null })]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('shows a dash when no salary information is present', () => {
    render(
      <OfferTable
        offers={[makeOffer({ salary_min: null, salary_max: null })]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('sorts offers by posted date, newest first', () => {
    const older = makeOffer({ id: 1, title: 'Older', posted_at: '2026-01-01T00:00:00Z' });
    const newer = makeOffer({ id: 2, title: 'Newer', posted_at: '2026-06-01T00:00:00Z' });

    render(
      <OfferTable
        offers={[older, newer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Newer');
    expect(rows[1]).toHaveTextContent('Older');
  });

  it('renders a score badge for an offer with a score', () => {
    const offer = makeOffer({ id: 1, score_percent: 92 });
    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('92%')).toBeInTheDocument();
  });

  it('renders the not-yet-scored badge for an offer with no score', () => {
    const offer = makeOffer({ id: 1, score_percent: null });
    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
  });

  it("opens the drawer with that offer's breakdown when its badge is clicked", async () => {
    const offer = makeOffer({ id: 1, score_percent: 92 });
    fetchOfferScoreMock.mockResolvedValue(
      makeScore({ score_percent: 92, rationale: 'Strong fit' }),
    );

    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /score 92%/i }));

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    expect(screen.getByText('Strong fit')).toBeInTheDocument();
    expect(fetchOfferScoreMock).toHaveBeenCalledWith(1);
  });

  it('does not open a drawer when clicking the not-yet-scored badge', async () => {
    const offer = makeOffer({ id: 1, score_percent: null });
    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/not yet scored/i));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(fetchOfferScoreMock).not.toHaveBeenCalled();
  });

  it('sorts by score ascending on the first header click, then descending on the second click', async () => {
    const offerMid = makeOffer({
      id: 1,
      title: 'OfferMid',
      posted_at: '2026-01-01T00:00:00Z',
      score_percent: 55,
    });
    const offerHigh = makeOffer({
      id: 2,
      title: 'OfferHigh',
      posted_at: '2026-02-01T00:00:00Z',
      score_percent: 92,
    });
    const offerLow = makeOffer({
      id: 3,
      title: 'OfferLow',
      posted_at: '2026-03-01T00:00:00Z',
      score_percent: 20,
    });

    render(
      <OfferTable
        offers={[offerMid, offerHigh, offerLow]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Score' }));
    let rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('OfferLow');
    expect(rows[1]).toHaveTextContent('OfferMid');
    expect(rows[2]).toHaveTextContent('OfferHigh');

    await userEvent.click(screen.getByRole('button', { name: 'Score' }));
    rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('OfferHigh');
    expect(rows[1]).toHaveTextContent('OfferMid');
    expect(rows[2]).toHaveTextContent('OfferLow');
  });

  it('keeps unscored offers last regardless of score sort direction', async () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored', score_percent: 77 });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored', score_percent: null });

    render(
      <OfferTable
        offers={[scoredOffer, unscoredOffer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: 'Score' }));
    let rows = screen.getAllByRole('row').slice(1);
    expect(rows[rows.length - 1]).toHaveTextContent('Unscored');

    await userEvent.click(screen.getByRole('button', { name: 'Score' }));
    rows = screen.getAllByRole('row').slice(1);
    expect(rows[rows.length - 1]).toHaveTextContent('Unscored');
  });

  it('renders both scored and unscored offers as given (filtering happens server-side)', () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored', score_percent: 77 });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored', score_percent: null });

    render(
      <OfferTable
        offers={[scoredOffer, unscoredOffer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByText('Scored')).toBeInTheDocument();
    expect(screen.getByText('Unscored')).toBeInTheDocument();
  });

  it('calls patchOffer and onOfferPatched when the Applied checkbox is clicked', async () => {
    const offer = makeOffer({ id: 1, applied: false });
    const updated = { ...offer, applied: true };
    patchOfferMock.mockResolvedValue(updated);

    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('checkbox', { name: /applied to/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { applied: true });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });

  it('calls patchOffer with hide:true and onOfferPatched when Hide is clicked', async () => {
    const offer = makeOffer({ id: 1, hide: false });
    const updated = { ...offer, hide: true };
    patchOfferMock.mockResolvedValue(updated);

    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /hide senior backend engineer/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { hide: true });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });

  it('shows a filled notes indicator when notes is non-empty and an outline indicator when null', () => {
    const withNotes = makeOffer({ id: 1, title: 'With Notes', notes: 'foo' });
    const withoutNotes = makeOffer({ id: 2, title: 'Without Notes', notes: null });

    render(
      <OfferTable
        offers={[withNotes, withoutNotes]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    expect(screen.getByRole('button', { name: /notes for with notes/i })).toHaveTextContent('📝');
    expect(screen.getByRole('button', { name: /notes for without notes/i })).toHaveTextContent(
      '📄',
    );
  });

  it('opens the notes editor, saves, and calls onOfferPatched', async () => {
    const offer = makeOffer({ id: 1, notes: null });
    const updated = { ...offer, notes: 'new notes' };
    patchOfferMock.mockResolvedValue(updated);

    render(
      <OfferTable
        offers={[offer]}
        loading={false}
        minScore=""
        onOfferPatched={onOfferPatchedMock}
      />,
    );

    await userEvent.click(screen.getByRole('button', { name: /notes for senior backend/i }));
    await userEvent.type(screen.getByRole('textbox'), 'new notes');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { notes: 'new notes' });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });
});
