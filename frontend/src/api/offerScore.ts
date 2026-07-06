import { apiClient } from './client';
import type { components } from './schema';

export type MatchScoreResponse = components['schemas']['MatchScoreResponse'];

export async function fetchOfferScore(offerId: number): Promise<MatchScoreResponse | null> {
  const { data, error } = await apiClient.GET('/offers/{offer_id}/score', {
    params: { path: { offer_id: offerId } },
  });

  if (error) {
    throw new Error(`failed to load score for offer ${offerId}`);
  }

  return data;
}
