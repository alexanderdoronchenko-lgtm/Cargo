const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * @param {number} ratingMin
 * @param {number} ratingMax
 * @param {number|undefined} userId telegram_id, when known — enables
 *   targeted-by-weakness selection for Emerald/Diamond subscribers server-side.
 * @returns {Promise<{
 *   puzzle_id: string, fen: string, solution: string[], rating: number,
 *   side_to_move: 'white'|'black', themes: string[],
 *   targeted_category: string|null, targeted_available: boolean,
 * }>}
 */
export async function fetchRandomPuzzle(ratingMin, ratingMax, userId) {
  const url = new URL('/api/puzzle/random', BASE_URL);
  url.searchParams.set('rating_min', Math.round(ratingMin));
  url.searchParams.set('rating_max', Math.round(ratingMax));
  if (userId != null) {
    url.searchParams.set('user_id', userId);
  }

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Puzzle fetch failed: ${response.status}`);
  }
  return response.json();
}

/**
 * @returns {Promise<{solved_today: number, streak_days: number, freeze_available: boolean, freeze_applied: boolean}>}
 */
export async function fetchPuzzleStats(userId) {
  const url = new URL('/api/puzzle/stats', BASE_URL);
  url.searchParams.set('user_id', userId);

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Puzzle stats fetch failed: ${response.status}`);
  }
  return response.json();
}

/**
 * Records a genuine solve (not a revealed solution) — updates today's
 * count and the streak server-side.
 * @returns {Promise<{solved_today: number, streak_days: number, freeze_available: boolean, freeze_applied: boolean}>}
 */
export async function recordPuzzleSolved(userId) {
  const url = new URL('/api/puzzle/solved', BASE_URL);
  url.searchParams.set('user_id', userId);

  const response = await fetch(url, { method: 'POST' });
  if (!response.ok) {
    throw new Error(`Puzzle solved recording failed: ${response.status}`);
  }
  return response.json();
}

/**
 * Emerald/Diamond only — the backend never sends the repertoire content to
 * an ineligible user, it just 403s. That 403 is surfaced here as
 * `error.status = 403` so the page can show the upsell stub instead of a
 * generic error.
 * @returns {Promise<{openings: Array}>}
 */
export async function fetchOpenings(userId) {
  const url = new URL('/api/openings', BASE_URL);
  if (userId != null) {
    url.searchParams.set('user_id', userId);
  }

  const response = await fetch(url);
  if (!response.ok) {
    const error = new Error(`Openings fetch failed: ${response.status}`);
    error.status = response.status;
    throw error;
  }
  return response.json();
}
