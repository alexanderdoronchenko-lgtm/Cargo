import { useCallback, useEffect, useRef, useState } from 'react';
import { Chess } from 'chess.js';
import Board from '../components/Board';
import { fetchRandomPuzzle, fetchPuzzleStats, recordPuzzleSolved } from '../lib/api';
import { getPuzzleRating, getSearchWindow, updatePuzzleRating } from '../lib/puzzleRating';
import { getTelegramUser } from '../lib/telegram';

const REPLY_DELAY_MS = 400;
const REVEAL_STEP_MS = 600;

// Mirrors services/puzzle_category_service.CATEGORY_LABELS_RU on the
// backend — the API returns category keys, not display text, so the two
// stay in sync deliberately rather than duplicating Russian strings there.
const CATEGORY_LABELS = {
  tactics: 'тактика',
  endgame: 'эндшпиль',
  opening: 'дебютные ошибки',
  positional: 'позиционное понимание',
};

function applyUci(fen, uci) {
  const game = new Chess(fen);
  game.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci.slice(4) || 'q' });
  return game.fen();
}

// Russian day-count pluralization: 1 день, 2-4 дня, 5-20 дней, 21 день, ...
function pluralizeDays(n) {
  const mod10 = n % 10;
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 14) return 'дней';
  if (mod10 === 1) return 'день';
  if (mod10 >= 2 && mod10 <= 4) return 'дня';
  return 'дней';
}

export default function PuzzlesPage() {
  const [status, setStatus] = useState('loading'); // loading | playing | failed | solved | error
  const [playerRating, setPlayerRating] = useState(() => getPuzzleRating());
  const [puzzle, setPuzzle] = useState(null);
  const [fen, setFen] = useState(null);
  const [solutionIndex, setSolutionIndex] = useState(0);
  const [wrongSquares, setWrongSquares] = useState(null);
  const [solvedByUser, setSolvedByUser] = useState(true);
  const [streakStats, setStreakStats] = useState(null);
  const ratingScoredRef = useRef(false);
  const userIdRef = useRef(getTelegramUser()?.id);

  const loadPuzzle = useCallback(async (rating) => {
    setStatus('loading');
    setWrongSquares(null);
    ratingScoredRef.current = false;
    try {
      const { ratingMin, ratingMax } = getSearchWindow(rating);
      const next = await fetchRandomPuzzle(ratingMin, ratingMax, userIdRef.current);
      setPuzzle(next);
      setFen(next.fen);
      setSolutionIndex(0);
      setStatus('playing');
    } catch {
      setStatus('error');
    }
  }, []);

  useEffect(() => {
    loadPuzzle(playerRating);
    if (userIdRef.current != null) {
      fetchPuzzleStats(userIdRef.current)
        .then(setStreakStats)
        .catch(() => {});
    }
    // Only on mount — subsequent loads are explicit (next puzzle / retry).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scoreAttempt = useCallback(
    (solved) => {
      if (ratingScoredRef.current || !puzzle) return;
      ratingScoredRef.current = true;
      setPlayerRating(updatePuzzleRating(playerRating, puzzle.rating, solved));
    },
    [playerRating, puzzle],
  );

  const recordSolve = useCallback(() => {
    if (userIdRef.current == null) return;
    recordPuzzleSolved(userIdRef.current)
      .then(setStreakStats)
      .catch(() => {});
  }, []);

  const handleMove = useCallback(
    (from, to) => {
      if (status !== 'playing' || !puzzle) return;

      const expected = puzzle.solution[solutionIndex];
      if (expected && expected.slice(0, 2) === from && expected.slice(2, 4) === to) {
        const afterUserMove = applyUci(fen, expected);
        const nextIndex = solutionIndex + 1;
        setFen(afterUserMove);
        setWrongSquares(null);

        if (nextIndex >= puzzle.solution.length) {
          setSolutionIndex(nextIndex);
          setSolvedByUser(true);
          setStatus('solved');
          scoreAttempt(true);
          recordSolve();
          return;
        }

        // Opponent's forced reply plays itself, then it's the solver's turn again.
        setSolutionIndex(nextIndex);
        setTimeout(() => {
          const reply = puzzle.solution[nextIndex];
          const afterReply = applyUci(afterUserMove, reply);
          const indexAfterReply = nextIndex + 1;
          setFen(afterReply);
          setSolutionIndex(indexAfterReply);
          if (indexAfterReply >= puzzle.solution.length) {
            setSolvedByUser(true);
            setStatus('solved');
            scoreAttempt(true);
            recordSolve();
          }
        }, REPLY_DELAY_MS);
        return;
      }

      // Legal chess move, but not the puzzle's solution: board stays on the
      // current fen (so it snaps back visually) and we flag it in red.
      scoreAttempt(false);
      setWrongSquares({ [from]: true, [to]: true });
      setStatus('failed');
    },
    [status, puzzle, fen, solutionIndex, scoreAttempt, recordSolve],
  );

  const revealSolution = useCallback(() => {
    if (!puzzle) return;
    setStatus('revealing');
    setWrongSquares(null);
    let index = solutionIndex;
    let currentFen = fen;

    const step = () => {
      if (index >= puzzle.solution.length) {
        setSolvedByUser(false);
        setStatus('solved');
        return;
      }
      currentFen = applyUci(currentFen, puzzle.solution[index]);
      index += 1;
      setFen(currentFen);
      setSolutionIndex(index);
      setTimeout(step, REVEAL_STEP_MS);
    };
    setTimeout(step, REVEAL_STEP_MS);
  }, [puzzle, fen, solutionIndex]);

  const customSquareStyles = wrongSquares
    ? Object.fromEntries(
        Object.keys(wrongSquares).map((square) => [
          square,
          { backgroundColor: 'rgba(220, 38, 38, 0.55)' },
        ]),
      )
    : undefined;

  return (
    <section className="space-y-4">
      <header>
        <p className="font-mono text-xs uppercase tracking-wider text-terracotta mb-1">!! Задачки</p>
        <h1 className="font-heading text-2xl font-bold">Тактические задачки</h1>
        <p className="text-ink-muted text-sm mt-2 max-w-[60ch]">
          Позиции из партий других игроков — найди лучший ход так же, как это делает движок в
          разборе. Сложность подстраивается под тебя: решил — следующая чуть сложнее, ошибся —
          чуть проще.
        </p>

        {streakStats && (
          <div className="mt-3 flex items-center justify-between font-mono text-xs">
            <span className="flex items-center gap-1 text-ink">
              {streakStats.streak_days > 0 ? (
                <>
                  🔥 {streakStats.streak_days} {pluralizeDays(streakStats.streak_days)} подряд
                  {streakStats.freeze_available && (
                    <span title="Заморозка доступна, если пропустишь день">🛡️</span>
                  )}
                </>
              ) : (
                <span className="text-ink-muted">Начни серию — реши первую задачку сегодня</span>
              )}
            </span>
            <span className="text-ink-muted">Сегодня решено: {streakStats.solved_today}</span>
          </div>
        )}
      </header>

      <div className="flex items-center justify-between font-mono text-xs text-ink-muted">
        <span>Твой рейтинг: {playerRating}</span>
        {puzzle && status !== 'loading' && <span>Рейтинг задачи: {puzzle.rating}</span>}
      </div>

      {status === 'error' && (
        <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-sm text-ink-muted">
          Не удалось загрузить задачку.
          <button
            type="button"
            onClick={() => loadPuzzle(playerRating)}
            className="mt-3 block w-full rounded-sm bg-terracotta py-2 font-medium text-on-accent"
          >
            Попробовать снова
          </button>
        </div>
      )}

      {status === 'loading' && (
        <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-sm text-ink-muted">
          Загружаю задачку...
        </div>
      )}

      {fen && status !== 'loading' && status !== 'error' && (
        <>
          <Board
            fen={fen}
            onMove={handleMove}
            orientation={puzzle?.side_to_move ?? 'white'}
            customSquareStyles={customSquareStyles}
          />

          {puzzle?.targeted_category && (
            <p className="text-center font-mono text-xs text-terracotta">
              🎯 Задача по твоей слабой стороне: {CATEGORY_LABELS[puzzle.targeted_category] ?? puzzle.targeted_category}
            </p>
          )}

          {status === 'failed' && (
            <div className="space-y-2 text-center">
              <p className="font-mono text-sm text-red-400">Неверно</p>
              <button
                type="button"
                onClick={revealSolution}
                className="rounded-sm border border-border bg-bg-elevated px-4 py-2 text-sm text-ink"
              >
                Показать решение
              </button>
            </div>
          )}

          {status === 'revealing' && (
            <p className="text-center font-mono text-sm text-ink-muted">Показываю решение...</p>
          )}

          {status === 'solved' && (
            <div className="space-y-2 text-center">
              <p className="font-mono text-sm text-terracotta">
                {solvedByUser ? 'Решено!' : 'Решение показано'}
              </p>
              <button
                type="button"
                onClick={() => loadPuzzle(playerRating)}
                className="rounded-sm bg-terracotta px-4 py-2 text-sm font-medium text-on-accent"
              >
                Следующая задача
              </button>
            </div>
          )}

          {puzzle && !puzzle.targeted_available && (
            <p className="rounded-sm border border-border bg-bg-elevated px-4 py-3 text-center text-xs text-ink-muted">
              Прицельный подбор по твоим слабостям доступен на Изумруде и выше — команда{' '}
              <code className="font-mono text-terracotta">/subscribe</code> в чате с ботом.
            </p>
          )}
        </>
      )}
    </section>
  );
}
