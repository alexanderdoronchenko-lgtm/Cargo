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
