const STORAGE_KEY = 'cm_puzzle_rating';
const DEFAULT_RATING = 1200;
const K_FACTOR = 24;
const SEARCH_WINDOW = 100;

// Dataset's actual rating span (see data/README.md) — clamp so the adaptive
// rating never drifts somewhere no puzzle will ever match.
const MIN_RATING = 400;
const MAX_RATING = 2800;

export function getPuzzleRating() {
  const stored = Number(localStorage.getItem(STORAGE_KEY));
  return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_RATING;
}

export function getSearchWindow(rating) {
  return {
    ratingMin: Math.max(MIN_RATING, rating - SEARCH_WINDOW),
    ratingMax: Math.min(MAX_RATING, rating + SEARCH_WINDOW),
  };
}

/**
 * Simple Elo-style update: the puzzle is treated as an opponent rated at
 * its own difficulty, solving it counts as a win, failing as a loss. This
 * is not Lichess's actual puzzle-rating algorithm (that's a full Glicko-2
 * system that also updates the puzzle's own rating) — just enough to push
 * difficulty up after a solve and down after a miss.
 */
export function updatePuzzleRating(playerRating, puzzleRating, solved) {
  const expected = 1 / (1 + 10 ** ((puzzleRating - playerRating) / 400));
  const actual = solved ? 1 : 0;
  const next = Math.round(playerRating + K_FACTOR * (actual - expected));
  const clamped = Math.min(MAX_RATING, Math.max(MIN_RATING, next));
  localStorage.setItem(STORAGE_KEY, String(clamped));
  return clamped;
}
