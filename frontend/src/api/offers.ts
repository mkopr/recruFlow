import { apiClient } from './client';
import type { components } from './schema';

export type OfferSummary = components['schemas']['OfferSummary'];
export type OfferListResponse = components['schemas']['OfferListResponse'];
export type IngestResponse = components['schemas']['IngestResponse'];
export type OfferEdit = components['schemas']['OfferEdit'];

export interface OfferListFilters {
  source?: string;
  remote?: boolean;
  seniority?: string;
  minSalary?: number;
  minScore?: number;
  showApplied?: boolean;
  showHidden?: boolean;
}

export interface OfferListPage {
  limit: number;
  offset: number;
}

export type OfferOrderBy = 'posted_at' | 'score_percent';
export type OfferOrder = 'asc' | 'desc';

export interface OfferListSort {
  orderBy: OfferOrderBy;
  order: OfferOrder;
}

export async function fetchOffers(
  filters: OfferListFilters,
  sort: OfferListSort,
  page: OfferListPage,
): Promise<OfferListResponse> {
  const { data, error } = await apiClient.GET('/offers', {
    params: {
      query: {
        source: filters.source,
        remote: filters.remote,
        seniority: filters.seniority,
        min_salary: filters.minSalary,
        min_score: filters.minScore,
        // Mirrors show_hidden's "excluded unless opted in" semantics (BUG33):
        // unchecked -> only not-applied offers; checked -> unfiltered, not
        // "only applied", so applied never maps to `true` here.
        applied: filters.showApplied ? undefined : false,
        show_hidden: filters.showHidden,
        order_by: sort.orderBy,
        order: sort.order,
        limit: page.limit,
        offset: page.offset,
      },
    },
  });

  if (error) {
    throw new Error('failed to load offers');
  }

  return data;
}

export async function triggerIngest(source: string): Promise<IngestResponse> {
  const { data, error } = await apiClient.POST('/ingest/{source}', {
    params: { path: { source } },
  });

  if (error) {
    throw new Error(`failed to trigger ingest for ${source}`);
  }

  return data;
}

export async function patchOffer(offerId: number, edit: OfferEdit): Promise<OfferSummary> {
  const { data, error } = await apiClient.PATCH('/offers/{offer_id}', {
    params: { path: { offer_id: offerId } },
    body: edit,
  });

  if (error) {
    throw new Error(`failed to update offer ${offerId}`);
  }

  return data;
}
