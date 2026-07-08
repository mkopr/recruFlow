import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { ScoreFilter } from './ScoreFilter';

describe('ScoreFilter', () => {
  it('calls onChange with the typed number', async () => {
    const onChange = vi.fn();
    render(<ScoreFilter value="" onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Minimum score %'), '5');

    expect(onChange).toHaveBeenLastCalledWith(5);
  });

  it('calls onChange with an empty string when cleared', async () => {
    const onChange = vi.fn();
    render(<ScoreFilter value={50} onChange={onChange} />);

    await userEvent.clear(screen.getByLabelText('Minimum score %'));

    expect(onChange).toHaveBeenCalledWith('');
  });

  it('accepts 0 as a valid value distinct from unset', () => {
    render(<ScoreFilter value={0} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Minimum score %')).toHaveValue(0);
  });
});
