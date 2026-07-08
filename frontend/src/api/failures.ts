import { apiClient } from './client';
import type { components } from './schema';

export type IngestionFailure = components['schemas']['IngestionFailureResponse'];
export type ScoringFailure = components['schemas']['ScoringFailureResponse'];
export type Failure = IngestionFailure | ScoringFailure;

export type FailureProcess = 'ingestion' | 'scoring';
export type FailureStatus = 'open' | 'resolved' | 'all';

export interface FailureListFilters {
  failureType?: string;
  source?: string;
  offerId?: number;
  profileId?: number;
  status?: FailureStatus;
}

export interface FailureListPage {
  limit: number;
  offset: number;
}

export interface FailureListResponse {
  items: Failure[];
  total: number;
}

export async function fetchFailures(
  process: FailureProcess,
  filters: FailureListFilters,
  page: FailureListPage,
): Promise<FailureListResponse> {
  const { data, error } = await apiClient.GET('/failures/{process}', {
    params: {
      path: { process },
      query: {
        failure_type: filters.failureType,
        source: filters.source,
        offer_id: filters.offerId,
        profile_id: filters.profileId,
        status: filters.status,
        limit: page.limit,
        offset: page.offset,
      },
    },
  });

  if (error) {
    throw new Error(`failed to load ${process} failures`);
  }

  return data;
}

export async function retryFailure(process: FailureProcess, failureId: number): Promise<Failure> {
  const { data, error } = await apiClient.POST('/failures/{process}/{failure_id}/retry', {
    params: { path: { process, failure_id: failureId } },
  });

  if (error) {
    throw new Error(`failed to retry ${process} failure ${failureId}`);
  }

  return data;
}
