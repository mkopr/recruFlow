import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as gradeAlertPrefsModule from '../lib/gradeAlertPrefs';
import * as soundModule from '../lib/sound';
import { NotificationsSection } from './NotificationsSection';

vi.mock('../lib/gradeAlertPrefs', () => ({
  loadGradeAlertPrefs: vi.fn(),
  saveGradeAlertPrefs: vi.fn(),
}));

vi.mock('../lib/sound', () => ({
  ALERT_SOUNDS: ['blip', 'chime', 'arpeggio'],
  playAlertSound: vi.fn(),
}));

const loadGradeAlertPrefsMock = vi.mocked(gradeAlertPrefsModule.loadGradeAlertPrefs);
const saveGradeAlertPrefsMock = vi.mocked(gradeAlertPrefsModule.saveGradeAlertPrefs);
const playAlertSoundMock = vi.mocked(soundModule.playAlertSound);

beforeEach(() => {
  loadGradeAlertPrefsMock.mockReset();
  saveGradeAlertPrefsMock.mockReset();
  playAlertSoundMock.mockReset();
  loadGradeAlertPrefsMock.mockReturnValue({ sound: 'chime', volume: 0.5, muted: false });
});

describe('NotificationsSection', () => {
  it('Test sound button calls playAlertSound with the selected sound and current volume', async () => {
    render(<NotificationsSection />);

    await userEvent.click(screen.getByRole('button', { name: 'Test sound' }));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0.5);
  });

  it('changing the volume persists immediately via saveGradeAlertPrefs', async () => {
    render(<NotificationsSection />);

    fireEvent.change(screen.getByRole('slider'), { target: { value: '0.9' } });

    expect(saveGradeAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'chime',
      volume: 0.9,
      muted: false,
    });
  });

  it('changing the sound persists immediately via saveGradeAlertPrefs', async () => {
    render(<NotificationsSection />);

    const select = screen.getByRole('combobox');
    await userEvent.selectOptions(select, 'arpeggio');

    expect(saveGradeAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'arpeggio',
      volume: 0.5,
      muted: false,
    });
  });

  it('mute toggle sets muted true without altering the stored volume value', async () => {
    render(<NotificationsSection />);

    await userEvent.click(screen.getByRole('checkbox'));

    expect(saveGradeAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'chime',
      volume: 0.5,
      muted: true,
    });
  });
});
