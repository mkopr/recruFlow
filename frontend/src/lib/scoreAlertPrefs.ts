import { ALERT_SOUNDS, type AlertSound } from './sound';

export interface ScoreAlertPrefs {
  sound: AlertSound;
  volume: number;
  muted: boolean;
  minScorePercent: number;
}

const STORAGE_KEY = 'recruflow.scoreAlertPrefs';

function defaultPrefs(): ScoreAlertPrefs {
  return { sound: 'chime', volume: 0.5, muted: false, minScorePercent: 90 };
}

function isAlertSound(value: unknown): value is AlertSound {
  return typeof value === 'string' && (ALERT_SOUNDS as string[]).includes(value);
}

function isValidPrefs(value: unknown): value is ScoreAlertPrefs {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    isAlertSound(candidate.sound) &&
    typeof candidate.volume === 'number' &&
    candidate.volume >= 0 &&
    candidate.volume <= 1 &&
    typeof candidate.muted === 'boolean' &&
    typeof candidate.minScorePercent === 'number' &&
    candidate.minScorePercent >= 0 &&
    candidate.minScorePercent <= 100
  );
}

export function loadScoreAlertPrefs(): ScoreAlertPrefs {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw === null) return defaultPrefs();

  try {
    const parsed: unknown = JSON.parse(raw);
    return isValidPrefs(parsed) ? parsed : defaultPrefs();
  } catch {
    return defaultPrefs();
  }
}

export function saveScoreAlertPrefs(prefs: ScoreAlertPrefs): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(prefs));
}
