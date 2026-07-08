import { FetchCadenceSection } from '../components/FetchCadenceSection';
import { NotificationsSection } from '../components/NotificationsSection';

export function SettingsPage() {
  return (
    <div className="mx-auto flex w-full max-w-screen-lg flex-col gap-6 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Fetch cadence: how often each connector automatically checks for new offers.
        </p>
      </header>
      <FetchCadenceSection />

      <header>
        <p className="text-sm text-[var(--color-text-muted)]">
          Notifications: play a sound when a new offer is scored above your chosen threshold.
        </p>
      </header>
      <NotificationsSection />
    </div>
  );
}
