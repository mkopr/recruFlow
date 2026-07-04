import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DealBreakersList } from './DealBreakersList';

describe('DealBreakersList', () => {
  it('renders existing deal-breaker strings', () => {
    render(<DealBreakersList dealBreakers={['No on-call']} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Deal breaker 1')).toHaveValue('No on-call');
  });

  it('add appends an empty entry', async () => {
    const onChange = vi.fn();
    render(<DealBreakersList dealBreakers={['No on-call']} onChange={onChange} />);

    await userEvent.click(screen.getByText('Add deal breaker'));

    expect(onChange).toHaveBeenCalledWith(['No on-call', '']);
  });

  it("editing an entry's text updates only that entry", async () => {
    const onChange = vi.fn();
    render(<DealBreakersList dealBreakers={['No on-call', 'No relocation']} onChange={onChange} />);

    await userEvent.type(screen.getByLabelText('Deal breaker 1'), '!');

    expect(onChange).toHaveBeenLastCalledWith(['No on-call!', 'No relocation']);
  });

  it('remove excludes an entry', async () => {
    const onChange = vi.fn();
    render(<DealBreakersList dealBreakers={['No on-call', 'No relocation']} onChange={onChange} />);

    await userEvent.click(screen.getAllByText('Remove')[0]);

    expect(onChange).toHaveBeenCalledWith(['No relocation']);
  });
});
