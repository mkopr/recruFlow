import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { playAlertSound } from './sound';

class FakeOscillator {
  type = '';
  frequency = { value: 0 };
  start = vi.fn();
  stop = vi.fn();
  connect = vi.fn();
}

class FakeGain {
  gain = { value: 0 };
  connect = vi.fn();
}

class FakeAudioContext {
  currentTime = 0;
  destination = {};
  close = vi.fn().mockResolvedValue(undefined);
  createOscillator = vi.fn(() => new FakeOscillator());
  createGain = vi.fn(() => new FakeGain());
}

let audioContextMock: ReturnType<typeof vi.fn>;
let lastContext: FakeAudioContext | undefined;

beforeEach(() => {
  lastContext = undefined;
  audioContextMock = vi.fn(function AudioContextMock(this: unknown) {
    lastContext = new FakeAudioContext();
    return lastContext;
  });
  vi.stubGlobal('AudioContext', audioContextMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('playAlertSound', () => {
  it('creates and starts an oscillator with gain derived from volume', () => {
    playAlertSound('blip', 0.5);

    expect(lastContext).toBeDefined();
    const context = lastContext!;
    expect(context.createOscillator).toHaveBeenCalled();
    const oscillator = context.createOscillator.mock.results[0]!.value as FakeOscillator;
    const gain = context.createGain.mock.results[0]!.value as FakeGain;

    expect(gain.gain.value).toBe(0.5);
    expect(oscillator.start).toHaveBeenCalled();
  });

  it('is a no-op at volume 0 and never constructs an AudioContext', () => {
    playAlertSound('chime', 0);

    expect(audioContextMock).not.toHaveBeenCalled();
  });
});
