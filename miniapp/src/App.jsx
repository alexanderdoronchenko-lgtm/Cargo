import { useEffect, useState } from 'react';
import { initTelegram, getTelegramUser, isInsideTelegram } from './lib/telegram';
import { LanguageProvider, useTranslation } from './lib/i18n';
import TabBar from './components/TabBar';
import AudioPlayer from './components/AudioPlayer';
import PuzzlesPage from './pages/PuzzlesPage';
import OpeningTrainerPage from './pages/OpeningTrainerPage';
import logoUrl from '../logo.svg';

const TABS = [
  { id: 'puzzles', labelKey: 'tab_puzzles', Page: PuzzlesPage },
  { id: 'trainer', labelKey: 'tab_trainer', Page: OpeningTrainerPage },
];

function AppShell() {
  const { t } = useTranslation();
  const [activeTab, setActiveTab] = useState(TABS[0].id);
  const [user, setUser] = useState(null);
  const [inTelegram, setInTelegram] = useState(false);

  useEffect(() => {
    initTelegram();
    setUser(getTelegramUser());
    setInTelegram(isInsideTelegram());
  }, []);

  const ActivePage = TABS.find((tab) => tab.id === activeTab).Page;
  const tabsWithLabels = TABS.map((tab) => ({ ...tab, label: t(tab.labelKey) }));

  return (
    <div className="flex min-h-screen flex-col bg-bg text-ink font-body">
      <header className="flex items-center gap-3 border-b border-border px-4 py-4">
        <img src={logoUrl} alt="" className="h-9 w-auto shrink-0" />
        <div className="min-w-0 flex-1">
          <p className="truncate font-heading text-lg font-bold leading-tight">Critical Moment</p>
          <p className="truncate font-mono text-xs text-ink-muted">
            {inTelegram
              ? user
                ? `id ${user.id} · ${user.username ? `@${user.username}` : user.first_name}`
                : t('header_in_telegram')
              : t('header_not_in_telegram')}
          </p>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto px-4 py-5">
        <ActivePage />
      </main>

      <AudioPlayer />

      <TabBar tabs={tabsWithLabels} active={activeTab} onChange={setActiveTab} />
    </div>
  );
}

export default function App() {
  return (
    <LanguageProvider>
      <AppShell />
    </LanguageProvider>
  );
}
