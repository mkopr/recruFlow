import { ConnectorSettingsSection } from '../components/ConnectorSettingsSection';
import { NotificationsSection } from '../components/NotificationsSection';
import { OfferCleanupSection } from '../components/OfferCleanupSection';

export function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-screen-lg flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Connectors: select a job board below to configure its fetch cadence, date range,
          auto-fetch, and stop/start state — one connector's settings shown at a time.
        </p>
      </header>
      <ConnectorSettingsSection />

      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Offer cleanup: permanently delete offers posted before a chosen date, skipping any offer
          that's part of your application pipeline.
        </p>
      </header>
      <OfferCleanupSection />

      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Notifications: play a sound when a new offer is scored above your chosen threshold.
        </p>
      </header>
      <NotificationsSection />
    </div>
  );
}
