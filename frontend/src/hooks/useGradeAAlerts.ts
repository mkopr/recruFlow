import { useEffect } from 'react';

import { baseUrl } from '../api/client';
import { loadGradeAlertPrefs } from '../lib/gradeAlertPrefs';
import { playAlertSound } from '../lib/sound';

export function useGradeAAlerts(): void {
  useEffect(() => {
    const source = new EventSource(`${baseUrl}/scoring/events`);

    const handleGradeA = () => {
      const prefs = loadGradeAlertPrefs();
      playAlertSound(prefs.sound, prefs.muted ? 0 : prefs.volume);
    };

    source.addEventListener('grade_a', handleGradeA);

    return () => {
      source.close();
    };
  }, []);
}
