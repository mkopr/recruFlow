import { renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as gradeAlertPrefsModule from '../lib/gradeAlertPrefs';
import * as soundModule from '../lib/sound';
import { useGradeAAlerts } from './useGradeAAlerts';

vi.mock('../lib/gradeAlertPrefs', () => ({
  loadGradeAlertPrefs: vi.fn(),
}));

vi.mock('../lib/sound', () => ({
  playAlertSound: vi.fn(),
}));

const loadGradeAlertPrefsMock = vi.mocked(gradeAlertPrefsModule.loadGradeAlertPrefs);
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

beforeEach(() => {
  loadGradeAlertPrefsMock.mockReset();
  playAlertSoundMock.mockReset();
  FakeEventSource.instances = [];
  vi.stubGlobal('EventSource', FakeEventSource);
});

describe('useGradeAAlerts', () => {
  it('constructs exactly one EventSource and closes it on unmount', () => {
    const { unmount } = renderHook(() => useGradeAAlerts());

    expect(FakeEventSource.instances).toHaveLength(1);
    const instance = FakeEventSource.instances[0]!;
    expect(instance.close).not.toHaveBeenCalled();

    unmount();

    expect(instance.close).toHaveBeenCalledTimes(1);
  });

  it('plays the loaded sound at the loaded volume when a grade_a event fires', () => {
    loadGradeAlertPrefsMock.mockReturnValue({ sound: 'chime', volume: 0.7, muted: false });
    renderHook(() => useGradeAAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('grade_a', new MessageEvent('grade_a', { data: '{}' }));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0.7);
  });

  it('plays at volume 0 (silently) when muted, rather than skipping playback', () => {
    loadGradeAlertPrefsMock.mockReturnValue({ sound: 'chime', volume: 0.7, muted: true });
    renderHook(() => useGradeAAlerts());

    const instance = FakeEventSource.instances[0]!;
    instance.emit('grade_a', new MessageEvent('grade_a', { data: '{}' }));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0);
  });
});
