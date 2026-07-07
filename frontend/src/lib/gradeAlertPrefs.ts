import { ALERT_SOUNDS, type AlertSound } from './sound';

export interface GradeAlertPrefs {
  sound: AlertSound;
  volume: number;
  muted: boolean;
}

const STORAGE_KEY = 'recruflow.gradeAlertPrefs';

function defaultPrefs(): GradeAlertPrefs {
  return { sound: 'chime', volume: 0.5, muted: false };
}

function isAlertSound(value: unknown): value is AlertSound {
  return typeof value === 'string' && (ALERT_SOUNDS as string[]).includes(value);
}

function isValidPrefs(value: unknown): value is GradeAlertPrefs {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    isAlertSound(candidate.sound) &&
    typeof candidate.volume === 'number' &&
    candidate.volume >= 0 &&
    candidate.volume <= 1 &&
    typeof candidate.muted === 'boolean'
  );
}

export function loadGradeAlertPrefs(): GradeAlertPrefs {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return defaultPrefs();

  try {
    const parsed: unknown = JSON.parse(raw);
    return isValidPrefs(parsed) ? parsed : defaultPrefs();
  } catch {
    return defaultPrefs();
  }
}

export function saveGradeAlertPrefs(prefs: GradeAlertPrefs): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}
