import { useEffect, useState } from 'react';

import {
  fetchScoringConfig,
  saveScoringConfig,
  type ScoringConfigData,
} from '../api/scoringConfig';
import {
  hasValidationErrors,
  validateScoringConfig,
  type ScoringConfigValidationErrors,
} from '../lib/scoringConfigValidation';

function emptyConfig(): ScoringConfigData {
  return { grade_a: 0, grade_b: 0, grade_c: 0, grade_d: 0 };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : 'failed to save scoring config';
}

export interface UseScoringConfigResult {
  config: ScoringConfigData;
  loading: boolean;
  saving: boolean;
  error: string | null;
  attemptedSubmit: boolean;
  validationErrors: ScoringConfigValidationErrors;
  setConfig: (next: ScoringConfigData) => void;
  save: () => Promise<boolean>;
}

export function useScoringConfig(): UseScoringConfigResult {
  const [config, setConfig] = useState<ScoringConfigData>(emptyConfig());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [attemptedSubmit, setAttemptedSubmit] = useState(false);

  useEffect(() => {
    let ignore = false;

    async function run() {
      try {
        const result = await fetchScoringConfig();
        if (ignore) return;
        setConfig(result);
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
  }, []);

  const validationErrors = validateScoringConfig(config);

  async function save(): Promise<boolean> {
    setAttemptedSubmit(true);
    if (hasValidationErrors(validateScoringConfig(config))) {
      return false;
    }

    setSaving(true);
    try {
      const response = await saveScoringConfig(config);
      setConfig(response);
      setError(null);
      return true;
    } catch (err) {
      setError(errorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  return {
    config,
    loading,
    saving,
    error,
    attemptedSubmit,
    validationErrors,
    setConfig,
    save,
  };
}
