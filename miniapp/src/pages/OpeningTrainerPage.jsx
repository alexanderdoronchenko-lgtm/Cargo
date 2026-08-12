import { useCallback, useEffect, useRef, useState } from 'react';
import { Chess } from 'chess.js';
import Board from '../components/Board';
import { fetchOpenings } from '../lib/api';
import { getTelegramUser } from '../lib/telegram';
import { useTranslation } from '../lib/i18n';

const OPPONENT_MOVE_DELAY_MS = 500;

// Repertoire files may carry assessment marks (e4!, Qh5?!) even though
// that's not part of strict SAN — chess.js only parses clean SAN, so
// they're stripped before every parse. Check/mate suffixes (+/#) are left
// alone since those genuinely are SAN.
function cleanSan(san) {
  return san.replace(/[!?]+$/, '');
}

function applySan(fen, san) {
  const game = new Chess(fen);
  game.move(cleanSan(san));
  return game.fen();
}

function randomChild(node) {
  const children = node.children ?? [];
  return children[Math.floor(Math.random() * children.length)];
}

export default function OpeningTrainerPage() {
  const { t } = useTranslation();
  // loading | restricted | error | playing | opponent-moving | failed | completed
  const [status, setStatus] = useState('loading');
  const [openingsPool, setOpeningsPool] = useState([]);
  const [currentRoot, setCurrentRoot] = useState(null);
  const [currentNode, setCurrentNode] = useState(null);
  const [moveIndex, setMoveIndex] = useState(0);
  const [fen, setFen] = useState(null);
  const [mistake, setMistake] = useState(null);
  const userIdRef = useRef(getTelegramUser()?.id);

  // Walks forward from (node, index, fen): skips through exhausted nodes by
  // picking a random child (the opponent's try isn't under the user's
  // control), stops and waits when it's the user's move, auto-plays and
  // recurses when it's the opponent's. Takes everything as parameters
  // rather than reading React state, so the setTimeout chain below never
  // acts on a stale render.
  const advance = useCallback((root, node, index, currentFen) => {
    while (index >= node.moves.length) {
      const next = randomChild(node);
      if (!next) {
        setCurrentNode(node);
        setFen(currentFen);
        setMistake(null);
        setStatus('completed');
        return;
      }
      node = next;
      index = 0;
    }

    setCurrentNode(node);
    setMoveIndex(index);
    setFen(currentFen);
    setMistake(null);

    const mover = new Chess(currentFen).turn() === 'w' ? 'white' : 'black';
    if (mover === root.side) {
      setStatus('playing');
      return;
    }

    setStatus('opponent-moving');
    setTimeout(() => {
      const nextFen = applySan(currentFen, node.moves[index]);
      advance(root, node, index + 1, nextFen);
    }, OPPONENT_MOVE_DELAY_MS);
  }, []);

  const startVariant = useCallback(
    (pool) => {
      const root = pool[Math.floor(Math.random() * pool.length)];
      setCurrentRoot(root);
      advance(root, root, 0, new Chess().fen());
    },
    [advance],
  );

  useEffect(() => {
    const userId = userIdRef.current;
    if (userId == null) {
      setStatus('restricted');
      return;
    }
    fetchOpenings(userId)
      .then(({ openings: pool }) => {
        if (!pool || pool.length === 0) {
          setStatus('error');
          return;
        }
        setOpeningsPool(pool);
        setStatus('loading');
        startVariant(pool);
      })
      .catch((err) => {
        setStatus(err.status === 403 ? 'restricted' : 'error');
      });
    // Only on mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleMove = useCallback(
    (from, to) => {
      if (status !== 'playing' || !currentNode || !currentRoot) return;

      const expectedSan = currentNode.moves[moveIndex];
      const expectedGame = new Chess(fen);
      const expectedMove = expectedGame.move(cleanSan(expectedSan));

      if (expectedMove.from === from && expectedMove.to === to) {
        advance(currentRoot, currentNode, moveIndex + 1, expectedGame.fen());
        return;
      }

      // Legal chess move, but not the repertoire's move: fen is left
      // untouched (Board snaps back) and the correct move + comment show.
      setMistake({ correctSan: cleanSan(expectedSan), comment: currentNode.comment });
      setStatus('failed');
    },
    [status, currentNode, currentRoot, moveIndex, fen, advance],
  );

  const continueAfterMistake = useCallback(() => {
    if (!currentNode || !currentRoot) return;
    const nextFen = applySan(fen, mistake.correctSan);
    advance(currentRoot, currentNode, moveIndex + 1, nextFen);
  }, [currentNode, currentRoot, moveIndex, fen, mistake, advance]);

  const nextVariant = useCallback(() => {
    startVariant(openingsPool);
  }, [openingsPool, startVariant]);

  return (
    <section className="space-y-4">
      <header>
        <p className="font-mono text-xs uppercase tracking-wider text-terracotta mb-1">{t('trainer_eyebrow')}</p>
        <h1 className="font-heading text-2xl font-bold">{t('tab_trainer')}</h1>
        <p className="text-ink-muted text-sm mt-2 max-w-[60ch]">{t('trainer_intro')}</p>
      </header>

      {status === 'restricted' && (
        <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-sm text-ink-muted">
          {t('trainer_restricted_prefix')}{' '}
          <code className="font-mono text-terracotta">/subscribe</code> {t('trainer_restricted_suffix')}
        </div>
      )}

      {status === 'error' && (
        <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-sm text-ink-muted">
          {t('trainer_load_error')}
        </div>
      )}

      {status === 'loading' && (
        <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-sm text-ink-muted">
          {t('trainer_loading')}
        </div>
      )}

      {fen && currentRoot && (
        <>
          <p data-testid="opening-caption" className="text-center font-mono text-xs text-ink-muted">
            {currentRoot.name}
            {currentNode && currentNode !== currentRoot ? ` · ${currentNode.name}` : ''}
          </p>

          <Board fen={fen} onMove={handleMove} orientation={currentRoot.side} />

          {status === 'opponent-moving' && (
            <p className="text-center font-mono text-sm text-ink-muted">{t('trainer_opponent_moving')}</p>
          )}

          {status === 'failed' && mistake && (
            <div className="space-y-2 rounded-md border border-border bg-bg-elevated p-4 text-center">
              <p className="font-mono text-sm text-red-400">
                {t('trainer_wrong_move', { move: mistake.correctSan })}
              </p>
              {mistake.comment && <p className="text-sm text-ink-muted">{mistake.comment}</p>}
              <button
                type="button"
                onClick={continueAfterMistake}
                className="rounded-sm border border-border bg-bg px-4 py-2 text-sm text-ink"
              >
                {t('trainer_continue')}
              </button>
            </div>
          )}

          {status === 'completed' && (
            <div className="space-y-2 text-center">
              <p className="font-mono text-sm text-terracotta">{t('trainer_completed')}</p>
              <button
                type="button"
                onClick={nextVariant}
                className="rounded-sm bg-terracotta px-4 py-2 text-sm font-medium text-on-accent"
              >
                {t('trainer_next_variant')}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
