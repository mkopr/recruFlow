import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as offerScoreApi from '../api/offerScore';
import * as offersApi from '../api/offers';
import type { OfferListSort, OfferSummary } from '../api/offers';
import * as scoreAlertPrefs from '../lib/scoreAlertPrefs';
import { OfferTable } from './OfferTable';

vi.mock('../api/offerScore', () => ({
  fetchOfferScore: vi.fn(),
}));

vi.mock('../api/offers', () => ({
  patchOffer: vi.fn(),
}));

vi.mock('../lib/scoreAlertPrefs', () => ({
  loadScoreAlertPrefs: vi.fn(),
}));

const fetchOfferScoreMock = vi.mocked(offerScoreApi.fetchOfferScore);
const patchOfferMock = vi.mocked(offersApi.patchOffer);
const loadScoreAlertPrefsMock = vi.mocked(scoreAlertPrefs.loadScoreAlertPrefs);
const onOfferPatchedMock = vi.fn();
const onScoreHeaderClickMock = vi.fn();
const onPostedHeaderClickMock = vi.fn();

function mockScoreAlertPrefs(minScorePercent: number): void {
  loadScoreAlertPrefsMock.mockReturnValue({
    sound: 'chime',
    volume: 0.5,
    muted: false,
    minScorePercent,
  });
}

const DEFAULT_SORT: OfferListSort = { orderBy: 'posted_at', order: 'desc' };

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

function renderTable(
  offers: OfferSummary[],
  overrides: {
    loading?: boolean;
    minScore?: number | '';
    sort?: OfferListSort;
  } = {},
) {
  render(
    <OfferTable
      offers={offers}
      loading={overrides.loading ?? false}
      minScore={overrides.minScore ?? ''}
      sort={overrides.sort ?? DEFAULT_SORT}
      onScoreHeaderClick={onScoreHeaderClickMock}
      onPostedHeaderClick={onPostedHeaderClickMock}
      onOfferPatched={onOfferPatchedMock}
    />,
  );
}

beforeEach(() => {
  fetchOfferScoreMock.mockReset();
  patchOfferMock.mockReset();
  patchOfferMock.mockResolvedValue(makeOffer());
  loadScoreAlertPrefsMock.mockReset();
  onOfferPatchedMock.mockReset();
  onScoreHeaderClickMock.mockReset();
  onPostedHeaderClickMock.mockReset();
  mockScoreAlertPrefs(90);
});

describe('OfferTable', () => {
  it('renders required columns with correct values', () => {
    renderTable([makeOffer()]);

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
    renderTable([]);

    expect(screen.getByText(/no offers yet/i)).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('does not show the empty state while loading with no offers yet', () => {
    renderTable([], { loading: true });

    expect(screen.queryByText(/no offers yet/i)).not.toBeInTheDocument();
  });

  it('shows a distinct empty state naming the active minimum score filter', () => {
    renderTable([], { minScore: 50 });

    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(
      screen.getByText(/no offers meet the minimum score filter \(50%\)/i),
    ).toBeInTheDocument();
  });

  it('formats a min-only salary range with a plus sign', () => {
    renderTable([makeOffer({ salary_min: 20000, salary_max: null })]);

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('formats a max-only salary range with "up to"', () => {
    renderTable([makeOffer({ salary_min: null, salary_max: 25000 })]);

    expect(screen.getByText('up to 25,000 PLN')).toBeInTheDocument();
  });

  it('defaults to PLN when currency is null but salary is present', () => {
    renderTable([makeOffer({ salary_min: 20000, salary_max: null, salary_currency: null })]);

    expect(screen.getByText('20,000+ PLN')).toBeInTheDocument();
  });

  it('shows a dash when no salary information is present', () => {
    renderTable([makeOffer({ salary_min: null, salary_max: null })]);

    expect(screen.getByText('-')).toBeInTheDocument();
  });

  it('renders offers in the order given by the server, without re-sorting client-side (BUG31)', () => {
    // The server owns ordering now; a low-scored offer appearing first here (as
    // it would under a score-desc sort) must not get client-side-reshuffled by
    // posted_at, or "page 2 of a score sort" would silently break again.
    const olderFirst = makeOffer({
      id: 1,
      title: 'ListedFirst',
      posted_at: '2026-01-01T00:00:00Z',
    });
    const newerSecond = makeOffer({
      id: 2,
      title: 'ListedSecond',
      posted_at: '2026-06-01T00:00:00Z',
    });

    renderTable([olderFirst, newerSecond]);

    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('ListedFirst');
    expect(rows[1]).toHaveTextContent('ListedSecond');
  });

  it('renders a score badge for an offer with a score', () => {
    renderTable([makeOffer({ id: 1, score_percent: 92 })]);

    expect(screen.getByText('92%')).toBeInTheDocument();
  });

  it('renders the not-yet-scored badge for an offer with no score', () => {
    renderTable([makeOffer({ id: 1, score_percent: null })]);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
  });

  it("opens the drawer with that offer's breakdown when its badge is clicked", async () => {
    const offer = makeOffer({ id: 1, score_percent: 92 });
    fetchOfferScoreMock.mockResolvedValue(
      makeScore({ score_percent: 92, rationale: 'Strong fit' }),
    );

    renderTable([offer]);

    await userEvent.click(screen.getByRole('button', { name: /score 92%/i }));

    await waitFor(() => expect(screen.getByRole('dialog')).toBeInTheDocument());
    expect(screen.getByText('Strong fit')).toBeInTheDocument();
    expect(fetchOfferScoreMock).toHaveBeenCalledWith(1);
  });

  it('does not open a drawer when clicking the not-yet-scored badge', async () => {
    const offer = makeOffer({ id: 1, score_percent: null });
    renderTable([offer]);

    expect(screen.getByText(/not yet scored/i)).toBeInTheDocument();
    await userEvent.click(screen.getByText(/not yet scored/i));

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(fetchOfferScoreMock).not.toHaveBeenCalled();
  });

  it('calls onScoreHeaderClick when the Score header is clicked, without re-sorting locally', async () => {
    const offerMid = makeOffer({ id: 1, title: 'OfferMid', score_percent: 55 });
    const offerHigh = makeOffer({ id: 2, title: 'OfferHigh', score_percent: 92 });
    const offerLow = makeOffer({ id: 3, title: 'OfferLow', score_percent: 20 });

    renderTable([offerMid, offerHigh, offerLow]);

    await userEvent.click(screen.getByRole('button', { name: 'Score' }));

    expect(onScoreHeaderClickMock).toHaveBeenCalledTimes(1);
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('OfferMid');
    expect(rows[1]).toHaveTextContent('OfferHigh');
    expect(rows[2]).toHaveTextContent('OfferLow');
  });

  it('shows an ascending indicator on the Score header when sorted by score ascending', () => {
    renderTable([makeOffer()], { sort: { orderBy: 'score_percent', order: 'asc' } });

    expect(screen.getByRole('button', { name: 'Score ▲' })).toBeInTheDocument();
  });

  it('shows a descending indicator on the Score header when sorted by score descending', () => {
    renderTable([makeOffer()], { sort: { orderBy: 'score_percent', order: 'desc' } });

    expect(screen.getByRole('button', { name: 'Score ▼' })).toBeInTheDocument();
  });

  it('shows no sort indicator on the Score header when sorted by posted date', () => {
    renderTable([makeOffer()], { sort: DEFAULT_SORT });

    expect(screen.getByRole('button', { name: 'Score' })).toBeInTheDocument();
  });

  it('calls onPostedHeaderClick when the Posted header is clicked, without re-sorting locally', async () => {
    const offerOlder = makeOffer({ id: 1, title: 'Older', posted_at: '2026-01-01T00:00:00Z' });
    const offerNewer = makeOffer({ id: 2, title: 'Newer', posted_at: '2026-06-01T00:00:00Z' });

    renderTable([offerOlder, offerNewer]);

    await userEvent.click(screen.getByRole('button', { name: 'Posted ▼' }));

    expect(onPostedHeaderClickMock).toHaveBeenCalledTimes(1);
    const rows = screen.getAllByRole('row').slice(1);
    expect(rows[0]).toHaveTextContent('Older');
    expect(rows[1]).toHaveTextContent('Newer');
  });

  it('shows an ascending indicator on the Posted header when sorted by posted date ascending', () => {
    renderTable([makeOffer()], { sort: { orderBy: 'posted_at', order: 'asc' } });

    expect(screen.getByRole('button', { name: 'Posted ▲' })).toBeInTheDocument();
  });

  it('shows a descending indicator on the Posted header when sorted by posted date descending', () => {
    renderTable([makeOffer()], { sort: DEFAULT_SORT });

    expect(screen.getByRole('button', { name: 'Posted ▼' })).toBeInTheDocument();
  });

  it('shows no sort indicator on the Posted header when sorted by score', () => {
    renderTable([makeOffer()], { sort: { orderBy: 'score_percent', order: 'desc' } });

    expect(screen.getByRole('button', { name: 'Posted' })).toBeInTheDocument();
  });

  it('renders both scored and unscored offers as given (filtering happens server-side)', () => {
    const scoredOffer = makeOffer({ id: 1, title: 'Scored', score_percent: 77 });
    const unscoredOffer = makeOffer({ id: 2, title: 'Unscored', score_percent: null });

    renderTable([scoredOffer, unscoredOffer]);

    expect(screen.getByText('Scored')).toBeInTheDocument();
    expect(screen.getByText('Unscored')).toBeInTheDocument();
  });

  it('calls patchOffer and onOfferPatched when the Applied checkbox is clicked', async () => {
    const offer = makeOffer({ id: 1, applied: false });
    const updated = { ...offer, applied: true };
    patchOfferMock.mockResolvedValue(updated);

    renderTable([offer]);

    await userEvent.click(screen.getByRole('checkbox', { name: /applied to/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { applied: true });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });

  it('calls patchOffer with hide:true and onOfferPatched when Hide is clicked', async () => {
    const offer = makeOffer({ id: 1, hide: false });
    const updated = { ...offer, hide: true };
    patchOfferMock.mockResolvedValue(updated);

    renderTable([offer]);

    await userEvent.click(screen.getByRole('button', { name: /hide senior backend engineer/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { hide: true });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });

  it('shows a filled notes indicator when notes is non-empty and an outline indicator when null', () => {
    const withNotes = makeOffer({ id: 1, title: 'With Notes', notes: 'foo' });
    const withoutNotes = makeOffer({ id: 2, title: 'Without Notes', notes: null });

    renderTable([withNotes, withoutNotes]);

    expect(screen.getByRole('button', { name: /notes for with notes/i })).toHaveTextContent('📝');
    expect(screen.getByRole('button', { name: /notes for without notes/i })).toHaveTextContent(
      '📄',
    );
  });

  it('opens the notes editor, saves, and calls onOfferPatched', async () => {
    const offer = makeOffer({ id: 1, notes: null });
    const updated = { ...offer, notes: 'new notes' };
    patchOfferMock.mockResolvedValue(updated);

    renderTable([offer]);

    await userEvent.click(screen.getByRole('button', { name: /notes for senior backend/i }));
    await userEvent.type(screen.getByRole('textbox'), 'new notes');
    await userEvent.click(screen.getByRole('button', { name: /save/i }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { notes: 'new notes' });
    await waitFor(() => expect(onOfferPatchedMock).toHaveBeenCalledWith(updated));
  });

  it('applies the highlight class to a row scoring at or above the alert threshold that has not been opened', () => {
    mockScoreAlertPrefs(80);
    renderTable([
      makeOffer({
        score_percent: 90,
        link_opened_at: null,
        canonical_url: 'https://example.com/jobs/1',
      }),
    ]);

    const row = screen.getAllByRole('row')[1];
    expect(row.className).toContain('card-accent');
  });

  it('does not highlight a row below the alert threshold', () => {
    mockScoreAlertPrefs(80);
    renderTable([makeOffer({ score_percent: 70 })]);

    const row = screen.getAllByRole('row')[1];
    expect(row.className).not.toContain('card-accent');
  });

  it('does not highlight an offer that has already been opened', () => {
    mockScoreAlertPrefs(80);
    renderTable([makeOffer({ score_percent: 95, link_opened_at: '2026-01-01T00:00:00Z' })]);

    const row = screen.getAllByRole('row')[1];
    expect(row.className).not.toContain('card-accent');
  });

  it('does not highlight an unscored offer regardless of threshold', () => {
    mockScoreAlertPrefs(0);
    renderTable([makeOffer({ score_percent: null })]);

    const row = screen.getAllByRole('row')[1];
    expect(row.className).not.toContain('card-accent');
  });

  it('does not highlight a high-scoring offer with no canonical_url', () => {
    mockScoreAlertPrefs(80);
    renderTable([makeOffer({ score_percent: 95, canonical_url: null, title: 'No Link Offer' })]);

    const row = screen.getAllByRole('row')[1];
    expect(row.className).not.toContain('card-accent');
    expect(screen.getByText('No Link Offer')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'No Link Offer' })).not.toBeInTheDocument();
  });

  it('clicking the title link on a highlighted offer optimistically clears the highlight and fires a fire-and-forget PATCH', async () => {
    mockScoreAlertPrefs(80);
    const offer = makeOffer({
      id: 1,
      score_percent: 90,
      link_opened_at: null,
      canonical_url: 'https://example.com/jobs/1',
    });
    let resolvePatch: (value: OfferSummary) => void = () => {};
    patchOfferMock.mockReturnValue(
      new Promise((resolve) => {
        resolvePatch = resolve;
      }),
    );

    renderTable([offer]);

    await userEvent.click(screen.getByRole('link', { name: offer.title }));

    expect(patchOfferMock).toHaveBeenCalledWith(1, { link_opened: true });
    expect(onOfferPatchedMock).toHaveBeenCalledTimes(1);
    const patchedArg = onOfferPatchedMock.mock.calls[0][0] as OfferSummary;
    expect(patchedArg.link_opened_at).not.toBeNull();

    resolvePatch(offer);
  });

  it('clicking the title link does not call preventDefault / does not block navigation', async () => {
    const offer = makeOffer({ canonical_url: 'https://example.com/jobs/1' });
    renderTable([offer]);

    const link = screen.getByRole('link', { name: offer.title });
    await userEvent.click(link);

    expect(link).toHaveAttribute('href', offer.canonical_url as string);
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('clicking the title link on an already-opened offer is a no-op — no duplicate PATCH', async () => {
    const offer = makeOffer({
      canonical_url: 'https://example.com/jobs/1',
      link_opened_at: '2026-01-01T00:00:00Z',
    });
    renderTable([offer]);

    await userEvent.click(screen.getByRole('link', { name: offer.title }));

    expect(patchOfferMock).not.toHaveBeenCalled();
  });
});
