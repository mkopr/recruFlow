import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { CvUploadControl } from './CvUploadControl';

function pickFile(input: HTMLElement, file: File) {
  return userEvent.upload(input, file);
}

describe('CvUploadControl', () => {
  it('shows "Uploading..." and disables the control while the upload promise is pending', async () => {
    let resolveUpload: () => void = () => {};
    const onUpload = vi.fn(
      () =>
        new Promise<void>((resolve) => {
          resolveUpload = resolve;
        }),
    );

    render(<CvUploadControl onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'cv.pdf', { type: 'application/pdf' });

    await pickFile(input, file);

    expect(screen.getByRole('button')).toHaveTextContent('Uploading...');
    expect(screen.getByRole('button')).toBeDisabled();

    resolveUpload();
    await waitFor(() => expect(screen.getByRole('button')).not.toBeDisabled());
  });

  it('calls onUpload with the picked File on a successful pick', async () => {
    const onUpload = vi.fn().mockResolvedValue(undefined);
    render(<CvUploadControl onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'cv.pdf', { type: 'application/pdf' });

    await pickFile(input, file);

    await waitFor(() => expect(onUpload).toHaveBeenCalledWith(file));
  });

  it("surfaces an inline error message when onUpload's promise rejects", async () => {
    const onUpload = vi.fn().mockRejectedValue(new Error('unsupported file type: .txt'));
    render(<CvUploadControl onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(['content'], 'cv.txt', { type: 'text/plain' });

    await userEvent.upload(input, file, { applyAccept: false });

    await waitFor(() =>
      expect(screen.getByText('unsupported file type: .txt')).toBeInTheDocument(),
    );
  });

  it('does not call onUpload twice for two rapid picks while one is already in flight', async () => {
    const onUpload = vi.fn(() => new Promise<void>(() => {}));
    render(<CvUploadControl onUpload={onUpload} />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    const fileA = new File(['content'], 'cv-a.pdf', { type: 'application/pdf' });
    const fileB = new File(['content'], 'cv-b.pdf', { type: 'application/pdf' });

    await pickFile(input, fileA);
    await pickFile(input, fileB);

    expect(onUpload).toHaveBeenCalledTimes(1);
  });
});
