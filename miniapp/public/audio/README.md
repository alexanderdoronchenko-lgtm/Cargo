# public/audio/

Drop background-music tracks here — `.mp3`, `.m4a`, `.ogg`, or `.wav`. No
naming convention required and no code changes needed: `GET
/api/audio/tracks` (api/main.py) lists whatever's in this folder at
request time, and the Mini App's player (src/components/AudioPlayer.jsx)
picks up whatever that returns.

Two things worth knowing:

- **Dev vs. production**: in `npm run dev`/`vite preview`, files added here
  are live immediately (Vite serves `public/` straight off disk). In a
  built/deployed app, `public/` is copied into `dist/` at build time, so a
  newly added track needs a rebuild + redeploy before it's actually
  servable — the *discovery logic* never needs touching, but the static
  file itself still has to ship.
- Currently expects `807488_zinali_sunshine-in-the-dawn-mist.mp3` — add it
  here and it'll show up as the player's track automatically.
