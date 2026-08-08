# lichess_puzzles_sample.csv

8,803 real Lichess puzzles, stratified by rating (up to 800 puzzles per
200-point rating band, all bands from ~600 to ~2800 kept even where the
source had fewer than 800 available) so the adaptive-difficulty puzzle
trainer has real puzzles to serve at every skill level, not just the
densely-populated 1200-1600 middle of the curve.

**Provenance**: `database.lichess.org` (the canonical source) and Kaggle/
Hugging Face mirrors were not reachable from the environment this was
built in. The data itself is still genuine, unmodified Lichess puzzles —
pulled from the `puzzle` field of
[mcognetta/lichess-combined-puzzle-game-db](https://github.com/mcognetta/lichess-combined-puzzle-game-db)'s
`combined_puzzle_db_first_50k.ndjson.bz2`, a 50,000-puzzle sample the
author checked directly into that repo (their own README explains why:
the full ~30GB dataset can't live in git, but this sample can). That
50k pool was then sampled down to this file — see
`scripts/import_puzzles.py` for the exact transform (applying each
puzzle's setup move up front so `fen`/`solution` are immediately usable).

Columns: `PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl`
— unmodified Lichess puzzle CSV schema.

To import: `python scripts/import_puzzles.py`
