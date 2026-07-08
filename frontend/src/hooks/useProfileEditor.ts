import { useEffect, useState } from 'react';

import {
  fetchProfile,
  saveProfile,
  uploadCv as uploadCvRequest,
  type ProfileData,
  type ProfileResponse,
} from '../api/profile';
import {
  hasValidationErrors,
  validateProfile,
  type ProfileValidationErrors,
} from '../lib/profileValidation';

const STORAGE_KEY = 'recruflow.profileEditor';

function emptyProfile(): ProfileData {
  return {
    skills: [],
    past_roles: [],
    education: [],
    certifications: [],
    languages: [],
    deal_breakers: [],
    core_skills: [],
    contract_type_preference: null,
    salary_min: null,
    salary_target: null,
    location_preference: null,
    remote_preference: null,
  };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to save profile';
}

function readCachedResponse(): ProfileResponse | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      parsed !== null &&
      typeof parsed === 'object' &&
      'id' in parsed &&
      'profile' in parsed &&
      'is_active' in parsed
    ) {
      return parsed as ProfileResponse;
    }
    return null;
  } catch {
    return null;
  }
}

function writeCachedResponse(response: ProfileResponse): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(response));
}

export interface UseProfileEditorResult {
  profile: ProfileData;
  profileId: number | null;
  isActive: boolean;
  loading: boolean;
  saving: boolean;
  error: string | null;
  attemptedSubmit: boolean;
  validationErrors: ProfileValidationErrors;
  setProfile: (next: ProfileData) => void;
  save: () => Promise<boolean>;
  activate: () => Promise<boolean>;
  uploadCv: (file: File) => Promise<void>;
}

export function useProfileEditor(): UseProfileEditorResult {
  const [cachedOnMount] = useState(() => readCachedResponse());
  const [profile, setProfile] = useState<ProfileData>(cachedOnMount?.profile ?? emptyProfile());
  const [profileId, setProfileId] = useState<number | null>(cachedOnMount?.id ?? null);
  const [isActive, setIsActive] = useState(cachedOnMount?.is_active ?? false);
  const [loading, setLoading] = useState(cachedOnMount === null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attemptedSubmit, setAttemptedSubmit] = useState(false);

  useEffect(() => {
    if (cachedOnMount) return;

    let ignore = false;

    async function run() {
      try {
        const result = await fetchProfile();
        if (ignore) return;
        if (result) {
          setProfile(result.profile);
          setProfileId(result.id);
          setIsActive(result.is_active);
          writeCachedResponse(result);
        }
        setError(null);
      } catch (err) {
        if (!ignore) {
          setError(errorMessage(err));
        }
      } finally {
        if (!ignore) {
          setLoading(false);
        }
      }
    }

    run();

    return () => {
      ignore = true;
    };
  }, [cachedOnMount]);

  const validationErrors = validateProfile(profile);

  async function persist(activateFlag: boolean): Promise<boolean> {
    setAttemptedSubmit(true);
    if (hasValidationErrors(validateProfile(profile))) {
      return false;
    }

    setSaving(true);
    try {
      const response = await saveProfile(profile, {
        profileId: profileId ?? undefined,
        activate: activateFlag,
      });
      writeCachedResponse(response);
      setProfile(response.profile);
      setProfileId(response.id);
      setIsActive(response.is_active);
      setError(null);
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function save(): Promise<boolean> {
    return persist(false);
  }

  async function activate(): Promise<boolean> {
    return persist(true);
  }

  async function uploadCv(file: File): Promise<void> {
    setSaving(true);
    try {
      const response = await uploadCvRequest(file);
      writeCachedResponse(response);
      setProfile(response.profile);
      setProfileId(response.id);
      setIsActive(response.is_active);
      setAttemptedSubmit(false);
      setError(null);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return {
    profile,
    profileId,
    isActive,
    loading,
    saving,
    error,
    attemptedSubmit,
    validationErrors,
    setProfile,
    save,
    activate,
    uploadCv,
  };
}
