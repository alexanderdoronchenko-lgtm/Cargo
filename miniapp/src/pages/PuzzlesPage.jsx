import { useCallback, useState } from 'react';
import { Chess } from 'chess.js';
import Board from '../components/Board';

export default function PuzzlesPage() {
  const [fen, setFen] = useState(() => new Chess().fen());
  const [lastMove, setLastMove] = useState(null);

  // Demo wiring for the Board component: PuzzlesPage owns the position and
  // decides what a move means. Once real puzzles exist, a wrong move here
  // would just not get committed (fen stays put) instead of always applying.
  const handleMove = useCallback((from, to) => {
    setFen((current) => {
      const game = new Chess(current);
      game.move({ from, to, promotion: 'q' });
      return game.fen();
    });
    setLastMove(`${from} → ${to}`);
  }, []);

  return (
    <section className="space-y-4">
      <header>
        <p className="font-mono text-xs uppercase tracking-wider text-terracotta mb-1">!! Задачки</p>
        <h1 className="font-heading text-2xl font-bold">Тактические задачки</h1>
        <p className="text-ink-muted text-sm mt-2 max-w-[60ch]">
          Позиции из критических моментов твоих собственных партий — найди лучший ход так же,
          как это делает движок в разборе.
        </p>
      </header>

      <Board fen={fen} onMove={handleMove} />
      {lastMove && (
        <p className="text-center font-mono text-xs text-ink-muted">Последний ход: {lastMove}</p>
      )}

      <div className="rounded-md border border-border bg-bg-elevated p-6 text-center text-ink-muted text-sm">
        Доска рабочая — задачки на реальных позициях появятся здесь позже.
      </div>
    </section>
  );
}
