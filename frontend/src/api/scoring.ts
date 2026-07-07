import { apiClient } from './client';
import type { components } from './schema';

export type ScoringStatus = components['schemas']['ScoringStatusResponse'];
export type BatchScoringResponse = components['schemas']['BatchScoringResponse'];

export async function fetchScoringStatus(): Promise<ScoringStatus> {
  const { data, error } = await apiClient.GET('/scoring/status');

  if (error) {
    throw new Error('failed to load scoring status');
  }

  return data;
}

export async function triggerBatchScoring(): Promise<BatchScoringResponse> {
  const { data, error } = await apiClient.POST('/score/batch');

  if (error) {
    throw new Error('failed to trigger scoring');
  }

  return data;
}
