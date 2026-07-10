import type { OfferListFilters, OfferListSort, OfferOrder, OfferOrderBy } from '../api/offers';

export interface OfferListPrefs {
  filters: OfferListFilters;
  minScore: number | '';
  sort: OfferListSort;
}

const STORAGE_KEY = 'recruflow.offerListPrefs';

const ORDER_BY_VALUES: OfferOrderBy[] = ['posted_at', 'score_percent'];
const ORDER_VALUES: OfferOrder[] = ['asc', 'desc'];

// Matches "Visibility"'s excluded-by-default semantics (BUG33): a first-ever
// visit, with nothing in storage yet, should still open on not-applied offers.
export function defaultOfferListPrefs(): OfferListPrefs {
  return {
    filters: { showApplied: false },
    minScore: '',
    sort: { orderBy: 'posted_at', order: 'desc' },
  };
}

function isOptionalString(value: unknown): value is string | undefined {
  return value === undefined || typeof value === 'string';
}

function isOptionalNumber(value: unknown): value is number | undefined {
  return value === undefined || typeof value === 'number';
}

function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || typeof value === 'boolean';
}

function isValidFilters(value: unknown): value is OfferListFilters {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    isOptionalString(candidate.source) &&
    isOptionalBoolean(candidate.remote) &&
    isOptionalString(candidate.seniority) &&
    isOptionalNumber(candidate.minSalary) &&
    isOptionalNumber(candidate.minScore) &&
    isOptionalBoolean(candidate.showApplied) &&
    isOptionalBoolean(candidate.showHidden)
  );
}

function isValidSort(value: unknown): value is OfferListSort {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.orderBy === 'string' &&
    ORDER_BY_VALUES.includes(candidate.orderBy as OfferOrderBy) &&
    typeof candidate.order === 'string' &&
    ORDER_VALUES.includes(candidate.order as OfferOrder)
  );
}

function isValidPrefs(value: unknown): value is OfferListPrefs {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    isValidFilters(candidate.filters) &&
    (candidate.minScore === '' || typeof candidate.minScore === 'number') &&
    isValidSort(candidate.sort)
  );
}

export function loadOfferListPrefs(): OfferListPrefs {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return defaultOfferListPrefs();

  try {
    const parsed: unknown = JSON.parse(raw);
    return isValidPrefs(parsed) ? parsed : defaultOfferListPrefs();
  } catch {
    return defaultOfferListPrefs();
  }
}

export function saveOfferListPrefs(prefs: OfferListPrefs): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}
