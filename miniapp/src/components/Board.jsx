import { useCallback, useEffect, useRef, useState } from 'react';
import { Chessboard } from 'react-chessboard';
import { Chess } from 'chess.js';

// Warm walnut/coffee board theme — deliberately brown, not the classic
// green or the cool blue-grey often used for "dark mode" boards, to stay
// in the same warm family as the rest of the app instead of introducing a
// clashing cool hue.
const DARK_SQUARE = '#4A3728';
const LIGHT_SQUARE = '#8C7460';

/**
 * Presentational chessboard: it owns no game state of its own. `fen` is the
 * single source of truth for what's displayed; a drag is only ever
 * validated against it via chess.js, never against some internal position
 * that could drift out of sync. Legal moves are reported via onMove — it's
 * up to the caller to decide what happens next (advance `fen`, reject a
 * wrong puzzle move, etc.).
 */
export default function Board({ fen, onMove, orientation = 'white' }) {
  const containerRef = useRef(null);
  const [boardWidth, setBoardWidth] = useState(320);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;

    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setBoardWidth(Math.floor(width));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const handlePieceDrop = useCallback(
    (sourceSquare, targetSquare) => {
      const game = new Chess(fen);
      let move;
      try {
        move = game.move({ from: sourceSquare, to: targetSquare, promotion: 'q' });
      } catch {
        return false; // chess.js throws on illegal moves — reject the drop
      }
      if (!move) return false;

      onMove?.(sourceSquare, targetSquare);
      return true;
    },
    [fen, onMove],
  );

  return (
    <div ref={containerRef} className="mx-auto w-full max-w-[480px]">
      <Chessboard
        id="critical-moment-board"
        position={fen}
        onPieceDrop={handlePieceDrop}
        boardWidth={boardWidth}
        boardOrientation={orientation}
        animationDuration={200}
        customBoardStyle={{
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-elevated)',
        }}
        customDarkSquareStyle={{ backgroundColor: DARK_SQUARE }}
        customLightSquareStyle={{ backgroundColor: LIGHT_SQUARE }}
        customDropSquareStyle={{
          boxShadow: 'inset 0 0 1px 4px var(--color-accent-terracotta)',
        }}
      />
    </div>
  );
}
