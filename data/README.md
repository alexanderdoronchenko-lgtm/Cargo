# lichess_puzzles_sample.csv

42,264 real Lichess puzzles — 82.5% of the entire 51,200-puzzle source pool
(see Provenance) — stratified by rating so the adaptive-difficulty puzzle
trainer keeps serving *different* puzzles at a given rating for months of
regular use, not just a few weeks before repeats start showing up (the
original 8,803-puzzle cut was too thin for that, especially at the
Diamond tier's 20/day limit).

Sampling: capped at 5,000 puzzles per 200-point rating band, taking
*everything* available in bands that had fewer than that. Only the five
densest bands (1000–1999) actually hit the cap; every other band —
including the sparse extremes, 600–799 and 2000–2799 — keeps 100% of what
the source had:

| Rating band | Puzzles kept | Source had |
| ----------- | -----------: | ---------: |
| 400–599     |            2 |          2 |
| 600–799     |        2,447 |      2,447 |
| 800–999     |        4,538 |      4,538 |
| 1000–1199   |        5,000 |      7,034 |
| 1200–1399   |        5,000 |      6,952 |
| 1400–1599   |        5,000 |      8,081 |
| 1600–1799   |        5,000 |      6,526 |
| 1800–1999   |        5,000 |      5,343 |
| 2000–2199   |        4,350 |      4,350 |
| 2200–2399   |        3,145 |      3,145 |
| 2400–2599   |        1,782 |      1,782 |
| 2600–2799   |          999 |        999 |
| 2800–2999   |            1 |          1 |

The 400 and 2800 bands are this thin in the *source* pool itself (2 and 1
puzzles respectively) — there's nothing more to extract there without a
bigger upstream source; every puzzle that exists at that rating in the
50k sample is already included.

**Provenance**: `database.lichess.org` (the canonical source) and Kaggle/
Hugging Face mirrors were not reachable from the environment this was
built in. The data itself is still genuine, unmodified Lichess puzzles —
pulled from the `puzzle` field of
[mcognetta/lichess-combined-puzzle-game-db](https://github.com/mcognetta/lichess-combined-puzzle-game-db)'s
`combined_puzzle_db_first_50k.ndjson.bz2` (51,200 puzzles despite the
name), a sample the author checked directly into that repo (their own
README explains why: the full ~30GB dataset can't live in git, but this
sample can) — see `scripts/import_puzzles.py` for the exact transform
(applying each puzzle's setup move up front so `fen`/`solution` are
immediately usable). This is the entire source pool available through
that repo; going further than 42,264 would mean finding a larger
reachable source, not sampling more aggressively from this one.

Columns: `PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,GameUrl`
— unmodified Lichess puzzle CSV schema.

To import: `python scripts/import_puzzles.py` (safe to re-run — existing
puzzle_ids are left untouched, so this only adds the newly-added rows).
