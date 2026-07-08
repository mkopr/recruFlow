import { useEffect } from 'react';

import { baseUrl } from '../api/client';
import { loadScoreAlertPrefs } from '../lib/scoreAlertPrefs';
import { playAlertSound } from '../lib/sound';

interface ScoreEventPayload {
  score_id: number;
  offer_id: number;
  title: string;
  company: string;
  score_percent: number;
}

export function useScoreAlerts(): void {
  useEffect(() => {
    const source = new EventSource(`${baseUrl}/scoring/events`);

    const handleScore = (event: MessageEvent<string>) => {
      const payload = JSON.parse(event.data) as ScoreEventPayload;
      const prefs = loadScoreAlertPrefs();
      if (payload.score_percent >= prefs.minScorePercent) {
        playAlertSound(prefs.sound, prefs.muted ? 0 : prefs.volume);
      }
    };

    source.addEventListener('score', handleScore);

    return () => {
      source.close();
    };
  }, []);
}
