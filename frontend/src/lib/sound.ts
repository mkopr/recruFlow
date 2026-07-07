export type AlertSound = 'blip' | 'chime' | 'arpeggio';

export const ALERT_SOUNDS: AlertSound[] = ['blip', 'chime', 'arpeggio'];

interface Note {
  frequency: number;
  startOffset: number;
  duration: number;
  type: OscillatorType;
}

const NOTES: Record<AlertSound, Note[]> = {
  blip: [{ frequency: 880, startOffset: 0, duration: 0.08, type: 'square' }],
  chime: [
    { frequency: 659, startOffset: 0, duration: 0.12, type: 'triangle' },
    { frequency: 988, startOffset: 0.1, duration: 0.16, type: 'triangle' },
  ],
  arpeggio: [
    { frequency: 523, startOffset: 0, duration: 0.08, type: 'square' },
    { frequency: 659, startOffset: 0.08, duration: 0.08, type: 'square' },
    { frequency: 784, startOffset: 0.16, duration: 0.12, type: 'square' },
  ],
};

export function playAlertSound(sound: AlertSound, volume: number): void {
  if (volume <= 0) return;

  const context = new AudioContext();
  const notes = NOTES[sound];
  let latestEnd = context.currentTime;

  for (const note of notes) {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    oscillator.type = note.type;
    oscillator.frequency.value = note.frequency;
    gain.gain.value = volume;

    oscillator.connect(gain);
    gain.connect(context.destination);

    const startAt = context.currentTime + note.startOffset;
    const endAt = startAt + note.duration;
    oscillator.start(startAt);
    oscillator.stop(endAt);
    latestEnd = Math.max(latestEnd, endAt);
  }

  const closeAfter = (latestEnd - context.currentTime) * 1000;
  setTimeout(() => {
    void context.close();
  }, closeAfter);
}
