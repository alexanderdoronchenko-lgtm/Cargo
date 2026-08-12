import { createContext, useContext, useEffect, useMemo, useState } from 'react';
import en from '../locales/en';
import ru from '../locales/ru';
import { getTelegramUser } from './telegram';
import { fetchUserLanguage } from './api';

const translations = { en, ru };

export const DEFAULT_LANG = 'en';

// Mirrors locales.resolve_lang on the bot exactly: anything other than
// literally "ru" falls back to English.
export function resolveLang(languageCode) {
  return languageCode === 'ru' ? 'ru' : DEFAULT_LANG;
}

function translate(key, lang, vars) {
  const table = translations[lang] ?? translations[DEFAULT_LANG];
  let template = table[key] ?? translations[DEFAULT_LANG][key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      template = template.replaceAll(`{${name}}`, value);
    }
  }
  return template;
}

// Russian day-count pluralization: 1 день, 2-4 дня, 5-20 дней, 21 день, ...
// English only has singular/plural, so this stays a per-language function
// rather than a flat locale key — the bot's own t() has no built-in
// pluralization either, so this follows the same "handle it in code, not
// in the string table" pattern.
export function pluralizeDays(n, lang) {
  if (lang !== 'ru') return n === 1 ? 'day' : 'days';
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return 'дней';
  if (mod10 === 1) return 'день';
  if (mod10 >= 2 && mod10 <= 4) return 'дня';
  return 'дней';
}

// For bilingual data fields from the backend (e.g. an opening's name/
// comment in data/openings.json — {"ru": "...", "en": "..."}), not for
// locale keys. Same fallback order as translate(): requested language,
// then DEFAULT_LANG, then whatever's there.
export function pickLocalized(field, lang) {
  if (field == null) return '';
  if (typeof field === 'string') return field;
  return field[lang] ?? field[DEFAULT_LANG] ?? Object.values(field)[0] ?? '';
}

const LanguageContext = createContext({ lang: DEFAULT_LANG, t: (key) => key });

export function LanguageProvider({ children }) {
  const telegramUser = getTelegramUser();
  // Instant guess from the Telegram client's own language, so there's no
  // flash of the wrong language while the DB-stored preference loads.
  const [lang, setLang] = useState(() => resolveLang(telegramUser?.language_code));

  useEffect(() => {
    if (telegramUser?.id == null) return;
    // The DB-stored preference (set via /language in the bot) is the
    // source of truth once it loads — same precedence as the bot's own
    // get_or_create_user: an existing row's stored language wins over
    // whatever language_code the client reports today.
    fetchUserLanguage(telegramUser.id, telegramUser.username, telegramUser.language_code)
      .then((resolved) => setLang(resolveLang(resolved)))
      .catch(() => {});
    // Only on mount — the user's language doesn't change mid-session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo(
    () => ({
      lang,
      t: (key, vars) => translate(key, lang, vars),
    }),
    [lang],
  );

  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useTranslation() {
  return useContext(LanguageContext);
}
