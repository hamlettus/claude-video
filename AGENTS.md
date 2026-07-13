# claude-video / watch skill

Agent Skills package that gives an agent a video input. Installable across Claude Code (most common host), Codex, Cursor, GitHub Copilot, and 50+ other [Agent Skills](https://agentskills.io) hosts. Pure-stdlib Python that orchestrates `yt-dlp` + `ffmpeg` and an optional Whisper API.

## Structure

- `skills/watch/SKILL.md` — canonical skill contract the model reads when `/watch` fires. Source of truth for behavior across every host.
- `skills/watch/scripts/watch.py` — entry point; orchestrates download → frames → transcript.
- `skills/watch/scripts/{download,frames,transcribe,whisper,setup,config}.py` — yt-dlp wrapper, ffmpeg frame extraction + auto-fps, caption/Whisper transcription, preflight/installer, shared config.
- `skills/watch/scripts/build-skill.sh` — builds `dist/watch.skill` for claude.ai upload (dev-only).
- `skills/shorts/SKILL.md` — contract for `/shorts`, the autonomous stick-figure shorts factory built on top of `/watch`.
- `skills/shorts/scripts/stickman.py` — pure-stdlib animation engine: framebuffer rasterizer + stick-figure rig + built-in 5×7 font + storyboard→frames. No third-party deps; PNG export makes it testable without ffmpeg.
- `skills/shorts/scripts/soundtrack.py` — pure-stdlib procedural audio: synthesizes a royalty-free chiptune bed (bass + arpeggio + kick/hats) to a WAV via stdlib `wave`. Same "generate the media from scratch" ethos as stickman; `animate.py --soundtrack` and `pipeline build --soundtrack` mux it so shorts aren't silent.
- `skills/shorts/scripts/{animate,trending,voiceover,publish,pipeline,setup,shorts_config}.py` — ffmpeg encode (frames piped as raw rgb24), yt-dlp trending discovery + dedup, optional TTS, credential-gated dry-run/live publishers (YouTube/IG/FB), orchestrator + ledger, preflight/installer, shared config. `shorts_config.py` is deliberately name-distinct from watch's `config.py` so both skills coexist in one pytest process.
- `skills/shorts/examples/` — a complete worked short (`side-project.storyboard.json` + `.meta.json` + README): 43s/8 scenes, every pose, two actors, off-screen staging, props, per-scene backgrounds. Renders as a template.
- `hooks/` — Claude Code SessionStart setup-status hook (Claude Code only).
- `.claude-plugin/` — `plugin.json` + `marketplace.json` (Claude Code plugin + local marketplace).
- `.codex-plugin/plugin.json` — Codex/agents manifest; `"skills": "./skills/"` points the Agent Skills CLI at the self-contained skill folder.
- `.agents/plugins/marketplace.json` — agents marketplace listing pointing at the repo-root plugin.
- `CLAUDE.md` → `@AGENTS.md` — generic-agent entry point.
- `tests/` — pytest suite (ffmpeg-synthesized clips; no network).

## Orientation

- Two skills ship from this repo. `/watch` gives the agent a video input; `/shorts` is an autonomous pipeline (discover trending → `/watch` to understand → model authors a storyboard → `stickman` renders original stick-figure animation → package → dry-run/live publish). Both are self-contained folders under `skills/` and are auto-discovered as one plugin.
- **`/shorts` publishes original animation, never the source footage.** The source is research only; `publish.py` is dry-run unless `--live`, and only touches platforms whose credentials exist. Keep that gate — do not add an auto-live path.
- The product is the slash-command-invoked skill (`/watch <url-or-path> [question]`), not a CLI. `scripts/watch.py` is implementation. Features must work across every harness the skill installs into, not just Claude Code.
- **The skill is one self-contained folder: `skills/watch/`.** SKILL.md and `scripts/` are siblings inside it. This is what lets `npx skills add` copy a working skill as a unit — do NOT move SKILL.md or `scripts/` back to the repo root, or non-Claude installers will copy SKILL.md without the scripts.
- **Path resolution is harness-agnostic.** SKILL.md resolves `SKILL_DIR` as the directory of the SKILL.md the model just Read, then runs `${SKILL_DIR}/scripts/...`. Do NOT reintroduce `${CLAUDE_SKILL_DIR}` (Claude-Code-only) — it is unset on Codex/Cursor/agents and breaks every script call there.
- **No `commands/` wrapper.** `/watch` is derived from SKILL.md frontmatter (`name: watch` + `user-invocable: true`). A separate command file creates a duplicate slash command.

## Install surfaces

| Surface | Install |
|---------|---------|
| Claude Code | `/plugin marketplace add bradautomates/claude-video` then `/plugin install watch@claude-video` |
| Codex / Cursor / Copilot / +50 | `npx skills add bradautomates/claude-video -g` |
| claude.ai (web) | upload `dist/watch.skill` (built by `skills/watch/scripts/build-skill.sh`) |

## Commands

```bash
# Tests (stdlib + pytest; ffmpeg required for frame tests)
.venv/bin/pytest -q                # or: python3 -m pytest -q

# Build the claude.ai upload bundle (archives skills/watch/ as the bundle root)
bash skills/watch/scripts/build-skill.sh   # → dist/watch.skill

# Dev: mirror the working tree into the installed Claude Code plugin cache
./dev-sync.sh                       # --dry-run to preview
```

## Rules

- Keep the version in sync across `skills/watch/SKILL.md` (frontmatter), `.claude-plugin/plugin.json`, and `.codex-plugin/plugin.json` when cutting a release.
- Releasing: tag `vX.Y.Z` and push the tag; `.github/workflows/release.yml` builds `dist/watch.skill` and attaches it to the GitHub release.
- Never commit real API keys or `.env` contents; keys live in `~/.config/watch/.env` (mode `0600`) at runtime.
