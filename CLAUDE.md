# Video-Edits

Read README.md for the full pipeline. Short version for agents:

- Footage: Tella MCP (`tella`) → export to `media/raw/`. Transcripts → `.srt` in `media/raw/`.
- Music/SFX: Epidemic Sound MCP (`epidemic-sound`) → `media/music/`, `media/sfx/`.
- Motion graphics: HyperFrames project in `motion/` (see motion/CLAUDE.md; use the `/hyperframes` skill).
  Render with `python3 scripts/vedit.py render-motion media/work/<name>.mp4 [--composition …] [--variables '{…}']`.
  Keep GSAP loaded from `assets/vendor/gsap.min.js` (no CDN).
- Assembly: `python3 scripts/vedit.py build project.json` (FFmpeg). Final output goes to `output/`.
- Never commit media; `media/*` and `output/*` are git-ignored on purpose.
