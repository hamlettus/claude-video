---
name: shorts
version: "0.1.0"
description: Autonomous stick-figure shorts factory. Finds trending long-form YouTube videos, understands them (via /watch), turns the best beat into an original stick-figure animation rendered to a 9:16 MP4, writes per-platform captions/hashtags, and publishes to YouTube Shorts, Instagram Reels, and Facebook Reels (dry-run until you provide credentials + explicitly go live).
argument-hint: "[discover | make <youtube-url> | run] [--live]"
allowed-tools: Bash, Read, AskUserQuestion
homepage: https://github.com/bradautomates/claude-video
repository: https://github.com/bradautomates/claude-video
author: bradautomates
license: MIT
user-invocable: true
---

# /shorts

Turn trending long-form YouTube videos into **original stick-figure viral shorts** and publish them to Facebook, Instagram, and YouTube — as hands-off as you want it. You (the model) are the creative director: you watch the source, decide the funniest/most surprising beat, and author a *storyboard*; bundled pure-Python scripts do the rest (animation, encoding, packaging, publishing).

The visual output is an **original animation**, not a re-upload of someone else's footage. The source video is only *research* — you retell one idea as stick figures. Keep it that way (see **Originality & rights** below).

## Resolve `SKILL_DIR` (do this before any command)

Every `python3 ...` command runs a bundled script under `SKILL_DIR/scripts/`. Set `SKILL_DIR` to the **absolute path of the directory containing THIS SKILL.md you just Read** — your harness told you that path. The scripts are always a direct sibling (`SKILL_DIR/scripts/…`), in every install layout (Claude Code plugin cache, `~/.codex/skills/shorts`, `~/.agents/skills/shorts`). Substitute the literal path for `${SKILL_DIR}` below. Guard once:

```bash
SKILL_DIR="<absolute path of the directory containing the SKILL.md you Read>"
[ -f "$SKILL_DIR/scripts/animate.py" ] || { echo "ERROR: scripts not found under $SKILL_DIR" >&2; exit 1; }
```

The sibling `/watch` skill provides the "understand the video" step. If it's installed, resolve its `WATCH_DIR` the same way; otherwise this skill downloads/reads captions itself via yt-dlp.

## Step 0 — Setup preflight (once per session)

```bash
python3 "${SKILL_DIR}/scripts/setup.py" --check   # exit 0 = ready (silent), 2 = install ffmpeg/yt-dlp
```

On exit 2, run the installer (auto-installs on macOS via brew; prints commands on Linux/Windows) and scaffold the config:

```bash
python3 "${SKILL_DIR}/scripts/setup.py"
```

**No API keys are required.** With none set, shorts render silent (captions carry the message) and every publish is a **dry-run**. Voiceover and live publishing are opt-in — add credentials to `~/.config/shorts/.env` only for what you want to enable. `--json` gives a machine-readable status.

## The pipeline

```
discover  →  understand  →  script  →  animate  →  package  →  publish
(yt-dlp)     (/watch)       (you!)     (stickman)   (you+meta)  (dry-run→live)
```

### 1. Discover — fresh trending long-form candidates

```bash
python3 "${SKILL_DIR}/scripts/trending.py" --max 5
```

Returns JSON candidates from the YouTube trending feed (override with `--source <playlist/channel url>`), filtered to long-form (`--min-seconds`, default 180) and **de-duplicated against everything already turned into a short** — so an autonomous loop never repeats a source. Pick the candidate with the clearest single "hook" (a surprising result, a mistake, a transformation, a strong opinion).

### 2. Understand — watch the source

Use the `/watch` skill on the chosen URL to get a timestamped transcript (and frames if useful):

```bash
python3 "${WATCH_DIR}/scripts/watch.py" "<youtube-url>" --detail transcript
```

Read the transcript. Find the **one** 20–45s idea that will hook a scroller in the first 2 seconds. You are summarizing/reacting/retelling — not lifting the video.

### 3. Script — author a storyboard (your job)

Write a `storyboard.json`. This is where the craft is: a punchy hook scene, 2–5 quick beats, a payoff. Schema:

```json
{
  "meta": { "width": 1080, "height": 1920, "fps": 30,
            "bg": "#0e1116", "fg": "#f5f5f5", "accent": "#ffca28" },
  "scenes": [
    {
      "duration": 2.5,
      "title":   "BIG BOLD HOOK",           // optional, centered upper third
      "caption": "what's happening down here", // optional, lower third, auto-wrapped
      "bg": "#141018",                        // optional per-scene background
      "props":   [ {"type":"ground","y":0.85}, {"type":"rect","x":0.1,"y":0.4,"w":0.3,"h":0.05,"color":"#ef5350"} ],
      "actors":  [
        { "id":"a", "color":"#ffca28", "scale":0.32, "cadence":2.0,
          "keyframes": [
            {"t":0.0, "x":0.30, "y":0.66, "pose":"walk"},
            {"t":1.2, "x":0.55, "y":0.66, "pose":"point"},
            {"t":2.5, "x":0.55, "y":0.66, "pose":"celebrate"}
          ] }
      ]
    }
  ]
}
```

Authoring rules that make it look good:
- **Coordinates are canvas fractions (0..1);** values slightly outside (roughly `-0.5..1.5`) are allowed so actors can walk in from / exit past an edge (e.g. `x:1.05` to enter from the right). Stand actors around `y:0.60–0.70` and keep `scale:0.28–0.36` so feet clear the lower-third captions.
- **Poses** (blend smoothly between keyframes): `idle, walk, run, wave, talk, point, jump, celebrate, think, shrug, fall, sit`. `walk`/`run` auto-cycle limbs; drive travel with the `x`/`y` on each keyframe.
- **Props**: `ground` (floor line), `rect`, `line`, `disk`. Use them as objects, doorways, phones, money, etc.
- **Captions** are the voice of the short — short, punchy, one idea per scene. The font is uppercase-styled and outlined for legibility on any background.
- Keep total duration **≤ 60s** (Reels/Shorts limit). 4–7 scenes is a good short.

Validate before rendering:

```bash
python3 "${SKILL_DIR}/scripts/animate.py" --validate storyboard.json
```

**Worked example:** `${SKILL_DIR}/examples/side-project.storyboard.json` is a complete 43s/8-scene short (with a matching `.meta.json`) exercising every pose, two actors, off-screen entrances, props, and per-scene backgrounds. Read it as a template — see `examples/README.md`.

### 4. Animate — render the MP4

```bash
# Always give a short sound — a silent short dies on Reels/Shorts:
python3 "${SKILL_DIR}/scripts/animate.py" storyboard.json -o out/short.mp4 --soundtrack upbeat
```

Frames are generated in pure Python and streamed straight into ffmpeg (no giant temp files). Preview a single frame without encoding: `--thumbnail thumb.png`.

**Give it sound (do this by default).** A silent short kills retention. `--soundtrack [upbeat|tense|chill]` generates a royalty-free chiptune bed (bass + arpeggio + kick/hats) **in pure Python** (`soundtrack.py`, stdlib `wave`), matched to the short's length and muxed in — no audio files, no API key, nothing to license. Pick the mood to fit the story (`tense` for suspense beats, `chill` for calmer ones). Skipped automatically if you pass `--music` or a `--voiceover`.

**Optional voiceover** (needs `OPENAI_API_KEY` in the config): synthesize narration, then mux it (narration takes priority; drop `--soundtrack` or layer `--music` ducked under it):

```bash
python3 "${SKILL_DIR}/scripts/voiceover.py" --file script.txt -o out/vo.mp3
python3 "${SKILL_DIR}/scripts/animate.py" storyboard.json -o out/short.mp4 --voiceover out/vo.mp3 --music bed.mp3
```

Background music is ducked under narration automatically. Provide your own royalty-free bed — do not lift the source video's audio.

### 5. Package — write per-platform metadata

Write a `meta.json` you'll hand to the publisher:

```json
{
  "title": "He lost $400 with one click 😳",
  "description": "The 3-second mistake nobody catches. #shorts",
  "hashtags": ["shorts", "reels", "storytime", "animation"],
  "caption": "optional single caption used verbatim for IG/FB (else built from the above)",
  "privacy": "private"
}
```

Titles: front-load the hook, ≤ ~80 chars. `privacy:"private"` is the safe default for the first live upload so you can review before making it public.

### 6. Publish — dry-run by default, live on purpose

```bash
# Dry-run every platform (no credentials needed) — shows exactly what WOULD post:
python3 "${SKILL_DIR}/scripts/publish.py" out/short.mp4 --meta out/meta.json

# Go live on a platform (needs that platform's credentials in the config):
python3 "${SKILL_DIR}/scripts/publish.py" out/short.mp4 --meta out/meta.json --platform youtube --live
```

- **YouTube Shorts**: resumable upload via Data API v3. Needs `YT_ACCESS_TOKEN` (OAuth, `youtube.upload` scope). Uploads the MP4 directly.
- **Instagram Reels** / **Facebook Reels**: the Graph API *pulls the file from a public URL*, so host the MP4 somewhere reachable and pass `--video-url https://…`. Needs `IG_USER_ID`+`IG_ACCESS_TOKEN` / `FB_PAGE_ID`+`FB_ACCESS_TOKEN`.

**`--live` is required for any real post, and only ever acts on the platforms whose credentials exist.** There is no path where a short goes public without an explicit `--live` on that specific run. Before your first `--live`, confirm with the user via `AskUserQuestion`.

### Orchestrate + log

`pipeline.py` wraps discover/build and keeps a ledger so autonomous runs are auditable:

```bash
python3 "${SKILL_DIR}/scripts/pipeline.py" discover --max 5
python3 "${SKILL_DIR}/scripts/pipeline.py" build --storyboard sb.json --meta meta.json \
    --source-id <ytid> --out out/short.mp4 [--voiceover-script script.txt]
python3 "${SKILL_DIR}/scripts/pipeline.py" ledger
```

`build` renders the short, writes a thumbnail + metadata, marks the source processed, and appends to `~/.config/shorts/state/ledger.json`.

## Running the "page" autonomously

A hands-off daily short = this loop, once per day:

1. `pipeline.py discover` → pick one fresh candidate.
2. `/watch` it → author `storyboard.json` + `meta.json` (the one step that needs your judgement).
3. `pipeline.py build` → render + log.
4. `publish.py … --live` per platform you've enabled.

Schedule it with the host's own scheduler — e.g. a Claude Code Routine / `create_trigger` firing daily, or plain `cron` calling a wrapper that invokes the agent. Keep `SHORTS_PUBLISH=dry-run` until you've reviewed a few outputs, then enable `--live` per platform. The processed-state file guarantees no repeats across runs.

## Originality & rights (read this)

- **Publish original animation, not the source footage.** Stick-figure retellings/summaries/reactions are transformative; re-uploading clips is not. This skill never muxes the source video's audio or frames into your short.
- Don't imitate a real person, channel, or brand's identity, and don't present the short as officially from them.
- Respect each platform's Terms and automation/spam policies; a per-day cadence with genuinely original creative is the intent, not mass reposting.
- You control the account — the skill only posts with credentials you supply and an explicit `--live`.

## Failure modes

- **`setup --check` exits 2** → run `setup.py` (installs ffmpeg/yt-dlp; scaffolds `.env`).
- **`trending.py` returns 0 candidates** → the feed had nothing above `--min-seconds`, or all were already processed. Lower `--min-seconds` or pass a different `--source`.
- **`animate.py` says ffmpeg missing** → run `setup.py`. Frame generation is pure Python; only the final encode needs ffmpeg.
- **Storyboard validation fails** → fix the reported scene/actor/keyframe (unknown pose, out-of-range coordinate, zero duration) and re-validate.
- **`publish` says "skipped: … not set"** → that platform has no credentials; add them to `~/.config/shorts/.env` (or leave it — the others still run).
- **IG/FB "needs --video-url"** → those APIs fetch the file themselves; host the MP4 publicly and pass its URL.

## Security & Permissions

**What this skill does:** runs `yt-dlp` (public trending metadata + transcript of a source you choose), `ffmpeg` (encodes locally generated frames), optionally calls a TTS API (only if `OPENAI_API_KEY` is set) and the YouTube/Meta publishing APIs (**only** with your credentials and an explicit `--live`). Reads/writes `~/.config/shorts/.env` (mode `0600`) for settings + credentials, and a state dir for the processed-list and ledger.

**What it does NOT do:** post anything without `--live`; upload the source video's footage or audio; access an account for which you didn't provide a token; print or log any credential. Bundled scripts: `trending.py`, `stickman.py` (animation engine), `animate.py` (encode), `voiceover.py` (optional TTS), `publish.py` (uploaders), `pipeline.py` (orchestrator), `setup.py` (preflight/installer). Review them before first use.
