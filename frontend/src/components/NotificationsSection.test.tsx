import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as scoreAlertPrefsModule from '../lib/scoreAlertPrefs';
import * as soundModule from '../lib/sound';
import { NotificationsSection } from './NotificationsSection';

vi.mock('../lib/scoreAlertPrefs', () => ({
  loadScoreAlertPrefs: vi.fn(),
  saveScoreAlertPrefs: vi.fn(),
}));

vi.mock('../lib/sound', () => ({
  ALERT_SOUNDS: ['blip', 'chime', 'arpeggio'],
  playAlertSound: vi.fn(),
}));

const loadScoreAlertPrefsMock = vi.mocked(scoreAlertPrefsModule.loadScoreAlertPrefs);
const saveScoreAlertPrefsMock = vi.mocked(scoreAlertPrefsModule.saveScoreAlertPrefs);
const playAlertSoundMock = vi.mocked(soundModule.playAlertSound);

beforeEach(() => {
  loadScoreAlertPrefsMock.mockReset();
  saveScoreAlertPrefsMock.mockReset();
  playAlertSoundMock.mockReset();
  loadScoreAlertPrefsMock.mockReturnValue({
    sound: 'chime',
    volume: 0.5,
    muted: false,
    minScorePercent: 90,
  });
});

describe('NotificationsSection', () => {
  it('Test sound button calls playAlertSound with the selected sound and current volume', async () => {
    render(<NotificationsSection />);

    await userEvent.click(screen.getByRole('button', { name: 'Test sound' }));

    expect(playAlertSoundMock).toHaveBeenCalledWith('chime', 0.5);
  });

  it('changing the volume persists immediately via saveScoreAlertPrefs', async () => {
    render(<NotificationsSection />);

    fireEvent.change(screen.getByRole('slider'), { target: { value: '0.9' } });

    expect(saveScoreAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'chime',
      volume: 0.9,
      muted: false,
      minScorePercent: 90,
    });
  });

  it('changing the sound persists immediately via saveScoreAlertPrefs', async () => {
    render(<NotificationsSection />);

    const select = screen.getByRole('combobox');
    await userEvent.selectOptions(select, 'arpeggio');

    expect(saveScoreAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'arpeggio',
      volume: 0.5,
      muted: false,
      minScorePercent: 90,
    });
  });

  it('mute toggle sets muted true without altering the stored volume value', async () => {
    render(<NotificationsSection />);

    await userEvent.click(screen.getByRole('checkbox'));

    expect(saveScoreAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'chime',
      volume: 0.5,
      muted: true,
      minScorePercent: 90,
    });
  });

  it('changing the minimum score for alert persists immediately', async () => {
    render(<NotificationsSection />);

    fireEvent.change(screen.getByLabelText('Minimum score for alert (%)'), {
      target: { value: '75' },
    });

    expect(saveScoreAlertPrefsMock).toHaveBeenCalledWith({
      sound: 'chime',
      volume: 0.5,
      muted: false,
      minScorePercent: 75,
    });
  });
});
