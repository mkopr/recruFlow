import { apiClient } from './client';
import type { components } from './schema';

export type ScoringStatus = components['schemas']['ScoringStatusResponse'];

export async function fetchScoringStatus(): Promise<ScoringStatus> {
  const { data, error } = await apiClient.GET('/scoring/status');

  if (error) {
    throw new Error('failed to load scoring status');
  }

  return data;
}
