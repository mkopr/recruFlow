import { useState } from 'react';

import { deleteOffers, previewOfferCleanup } from '../api/offers';

interface CleanupPreview {
  wouldDelete: number;
  wouldSkip: number;
}

interface CleanupResult {
  deleted: number;
  skipped: number;
}

export function useOfferCleanup() {
  const [previewing, setPreviewing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<CleanupPreview | null>(null);
  const [result, setResult] = useState<CleanupResult | null>(null);

  async function loadPreview(olderThan: string): Promise<void> {
    setPreviewing(true);
    setError(null);
    try {
      const data = await previewOfferCleanup(olderThan);
      setPreview({ wouldDelete: data.would_delete, wouldSkip: data.would_skip });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to preview cleanup');
    } finally {
      setPreviewing(false);
    }
  }

  async function confirmDelete(olderThan: string): Promise<void> {
    setDeleting(true);
    setError(null);
    try {
      const data = await deleteOffers(olderThan);
      setResult({ deleted: data.deleted, skipped: data.skipped });
      setPreview(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'failed to delete offers');
    } finally {
      setDeleting(false);
    }
  }

  function cancelPreview(): void {
    setPreview(null);
  }

  return {
    previewing,
    deleting,
    error,
    preview,
    result,
    loadPreview,
    confirmDelete,
    cancelPreview,
  };
}
