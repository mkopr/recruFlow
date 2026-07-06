import { apiClient } from './client';
import type { components } from './schema';

export type ScoringConfigData = components['schemas']['ScoringConfig'];

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  return fallback;
}

export async function fetchScoringConfig(): Promise<ScoringConfigData> {
  const { data, error } = await apiClient.GET('/scoring-config');

  if (error) {
    throw new Error('failed to load scoring config');
  }

  return data;
}

export async function saveScoringConfig(config: ScoringConfigData): Promise<ScoringConfigData> {
  const { data, error } = await apiClient.PUT('/scoring-config', {
    body: config,
  });

  if (error) {
    throw new Error(detailMessage(error.detail, 'failed to save scoring config'));
  }

  return data;
}
