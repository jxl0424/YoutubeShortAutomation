# Background music

Every `.mp3` in this folder is in the daily short's music rotation — the CLI
picks one at random per run (never repeating back-to-back). Drop in more tracks
to widen the rotation; keep everything CC0 / public-domain so the channel stays
monetization-safe.

All current tracks are by **HoliznaCC0**, dedicated to the public domain under
**CC0 1.0 Universal** (no attribution required), from the *Public Domain Lofi*
album on Free Music Archive
(https://freemusicarchive.org/music/holiznacc0/public-domain-lofi). The artist
states: "This music is completely Public Domain, so use it how you want!"

Each was trimmed to a 60-second loop with a 2s fade-in / fade-out and re-encoded
at 128 kbps for the repo, then mixed under narration at low volume.

| File | Track title |
| --- | --- |
| `lofi-bubbles.mp3` | Bubbles ( Lofi , Bright , Relaxed ) |
| `lofi-tokyo-sunset.mp3` | Tokyo Sunset ( Lofi , Peaceful , Soft ) |
| `lofi-one-night-in-france.mp3` | One Night In France ( Lofi , Nostalgic , Chill ) |
| `lofi-calm-currents.mp3` | Calm Currents ( Lofi , Relax , Calm ) |
| `lofi-warm-fuzz.mp3` | Warm Fuzz ( LoFi , Retro ) |

Rotation folder is set as `video.music.dir` in `config/shorts.yaml`;
`video.music.path` remains the single-track fallback when the folder is empty.
