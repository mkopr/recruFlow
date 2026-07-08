import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as scoreAlertPrefsModule from '../lib/scoreAlertPrefs';
import * as soundModule from '../lib/sound';
import { useScoreAlerts } from './useScoreAlerts';

vi.mock('../lib/scoreAlertPrefs', () => ({
  loadScoreAlertPrefs: vi.fn(),
}));

vi.mock('../lib/sound', () => ({
  playAlertSound: vi.fn(),
}));

const loadScoreAlertPrefsMock = vi.mocked(scoreAlertPrefsModule.loadScoreAlertPrefs);
const playAlertSoundMock = vi.mocked(soundModule.playAlertSound);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  url: string;
  listeners: Record<string, ((event: MessageEvent) => void)[]> = {};
  close = vi.fn();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners[type] = [...(this.listeners[type] ?? []), listener];
  }

  emit(type: string, event: MessageEvent): void {
    for (const listener of this.listeners[type] ?? []) listener(event);
  }
}

function scoreEvent(scorePercent: number): MessageEvent {
  return new MessageEvent('score', {
    data: JSON.stringify({
      score_id: 1,
      offer_id: 2,
      title: 't',
      company: 'c',
      score_percent: scorePercent,
    }),
  });
}

beforeEach(() => {
  loadScoreAlertPrefsMock.mockReset();
  playAlertSoundMock.mockReset();
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

describe('useScoreAlerts', () => {
  it('constructs exactly one EventSource and closes it on unmount', () => {
    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
    const { unmount } = renderHook(() => useScoreAlerts());

    expect(FakeEventSource.instances).toHaveLength(1);
    const instance = FakeEventSource.instances[0]!;
    expect(instance.close).not.toHaveBeenCalled();

    unmount();

    expect(instance.close).toHaveBeenCalledTimes(1);
  });

  it('plays the loaded sound at the loaded volume when the score meets the threshold', () => {
    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.7,
      muted: false,
      minScorePercent: 90,
    });
    renderHook(() => useScoreAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('score', scoreEvent(95));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0.7);
  });

  it('does not play a sound when the score is below the threshold', () => {
    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.7,
      muted: false,
      minScorePercent: 90,
    });
    renderHook(() => useScoreAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('score', scoreEvent(70));

    expect(playAlertSoundMock).not.toHaveBeenCalled();
  });

  it('plays at volume 0 (silently) when muted and the score meets the threshold', () => {
    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.7,
      muted: true,
      minScorePercent: 90,
    });
    renderHook(() => useScoreAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('score', scoreEvent(95));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0);
  });

  it('re-reads the threshold from storage on each event, without reconnecting', () => {
    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
    renderHook(() => useScoreAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('score', scoreEvent(70));
    expect(playAlertSoundMock).not.toHaveBeenCalled();

    loadScoreAlertPrefsMock.mockReturnValue({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 60,
    });
    instance.emit('score', scoreEvent(70));

    expect(FakeEventSource.instances).toHaveLength(1);
    expect(playAlertSoundMock).toHaveBeenCalledTimes(1);
  });
});
