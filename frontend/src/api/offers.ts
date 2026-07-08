import { apiClient } from './client';
import type { components } from './schema';

export type OfferSummary = components['schemas']['OfferSummary'];
export type OfferListResponse = components['schemas']['OfferListResponse'];
export type IngestResponse = components['schemas']['IngestResponse'];

export interface OfferListFilters {
  source?: string;
  remote?: boolean;
  seniority?: string;
  minSalary?: number;
  minScore?: number;
}

export interface OfferListPage {
  limit: number;
  offset: number;
}

export async function fetchOffers(
  filters: OfferListFilters,
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
