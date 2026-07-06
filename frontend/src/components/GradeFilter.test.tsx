import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { GradeFilter } from './GradeFilter';

describe('GradeFilter', () => {
  it('calls onChange with the selected grade', async () => {
    const onChange = vi.fn();
    render(<GradeFilter value="" onChange={onChange} />);

    await userEvent.selectOptions(screen.getByLabelText('Minimum grade'), 'B');

    expect(onChange).toHaveBeenCalledWith('B');
  });

  it('calls onChange with an empty string when Any is selected', async () => {
    const onChange = vi.fn();
    render(<GradeFilter value="B" onChange={onChange} />);

    await userEvent.selectOptions(screen.getByLabelText('Minimum grade'), 'Any');

    expect(onChange).toHaveBeenCalledWith('');
  });

  it('renders all five grade options plus Any', () => {
    render(<GradeFilter value="" onChange={vi.fn()} />);

    const options = screen.getAllByRole('option');
    expect(options).toHaveLength(6);
    expect(options.map((option) => option.textContent)).toEqual(['Any', 'A', 'B', 'C', 'D', 'F']);
  });
});
