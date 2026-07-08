import { useState } from 'react';

import { loadScoreAlertPrefs, saveScoreAlertPrefs } from '../lib/scoreAlertPrefs';
import { ALERT_SOUNDS, playAlertSound, type AlertSound } from '../lib/sound';

export function NotificationsSection() {
  const [prefs, setPrefs] = useState(() => loadScoreAlertPrefs());

  const update = (next: Partial<typeof prefs>) => {
    const merged = { ...prefs, ...next };
    setPrefs(merged);
    saveScoreAlertPrefs(merged);
  };

  return (
    <div className="card flex flex-col gap-4 p-4">
      <label className="flex flex-col gap-1 text-sm">
        Minimum score for alert (%)
        <input
          type="number"
          min={0}
          max={100}
          step={1}
          className="input"
          value={prefs.minScorePercent}
          onChange={(e) => update({ minScorePercent: Number(e.target.value) })}
        />
      </label>

      <label className="flex flex-col gap-1 text-sm">
        Alert sound
        <select
          className="input"
          value={prefs.sound}
          onChange={(e) => update({ sound: e.target.value as AlertSound })}
        >
          {ALERT_SOUNDS.map((sound) => (
            <option key={sound} value={sound}>
              {sound}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 text-sm">
        Volume
        <input
          type="range"
          min="0"
          max="1"
          step="0.05"
          value={prefs.volume}
          onChange={(e) => update({ volume: Number(e.target.value) })}
        />
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={prefs.muted}
          onChange={(e) => update({ muted: e.target.checked })}
        />
        Mute
      </label>

      <div>
        <button
          type="button"
          className="btn"
          onClick={() => playAlertSound(prefs.sound, prefs.muted ? 0 : prefs.volume)}
        >
          Test sound
        </button>
      </div>
    </div>
  );
}
