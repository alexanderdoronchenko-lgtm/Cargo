const BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';

/**
 * @returns {Promise<{puzzle_id: string, fen: string, solution: string[], rating: number, side_to_move: 'white'|'black', themes: string[]}>}
 */
export async function fetchRandomPuzzle(ratingMin, ratingMax) {
  const url = new URL('/api/puzzle/random', BASE_URL);
  url.searchParams.set('rating_min', Math.round(ratingMin));
  url.searchParams.set('rating_max', Math.round(ratingMax));

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`Puzzle fetch failed: ${response.status}`);
  }
  return response.json();
}
