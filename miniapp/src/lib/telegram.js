import WebApp from '@twa-dev/sdk';

/**
 * Call once on app start. `initData` is only populated when the page is
 * actually opened inside a Telegram client, so outside of Telegram (plain
 * browser during development) everything here degrades to empty/null
 * rather than throwing.
 */
export function initTelegram() {
  WebApp.ready();
  WebApp.expand();
}

export function isInsideTelegram() {
  return Boolean(WebApp.initData);
}

/**
 * Convenience accessor for display purposes only (name, id for a "signed
 * in as ..." line). `id` here is the same telegram_id used as the primary
 * key across the bot's `users`/`subscriptions` tables.
 *
 * Never use this for anything that gates access or reads another user's
 * data — initDataUnsafe is exactly that, unsafe, since it can be edited
 * client-side. Send `getInitData()` to the backend instead and let it
 * verify the HMAC signature against the bot token before trusting the
 * user id it contains.
 */
export function getTelegramUser() {
  return WebApp.initDataUnsafe?.user ?? null;
}

/** Raw signed init data string, to be sent as-is to the backend for verification. */
export function getInitData() {
  return WebApp.initData || '';
}

export default WebApp;
