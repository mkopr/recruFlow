import { apiClient } from './client';
import type { components } from './schema';

export type ProfileData = components['schemas']['Profile'];
export type ProfileResponse = components['schemas']['ProfileResponse'];

function detailMessage(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  return fallback;
}

export async function fetchProfile(): Promise<ProfileResponse | null> {
  const { data, error } = await apiClient.GET('/profile');

  if (error) {
    throw new Error('failed to load profile');
  }

  return data;
}

export async function saveProfile(
  profile: ProfileData,
  opts: { profileId?: number; activate: boolean },
): Promise<ProfileResponse> {
  const { data, error } = await apiClient.PUT('/profile', {
    params: { query: { profile_id: opts.profileId, activate: opts.activate } },
    body: profile,
  });

  if (error) {
    throw new Error(detailMessage(error.detail, 'failed to save profile'));
  }

  return data;
}

export async function uploadCv(file: File): Promise<ProfileResponse> {
  const { data, error } = await apiClient.POST('/profile/upload', {
    body: { file } as unknown as components['schemas']['Body_upload_cv_profile_upload_post'],
    bodySerializer: () => {
      const form = new FormData();
      form.append('file', file);
      return form;
    },
  });

  if (error) {
    throw new Error(detailMessage(error.detail, 'failed to upload cv'));
  }

  return data;
}
