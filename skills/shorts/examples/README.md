# Example: a full worked short

A complete 43-second, 8-scene vertical short (1080×1920, 30fps) you can render
and study as a template.

- **`side-project.storyboard.json`** — the storyboard. A tidy narrative arc:
  hook title → "day 1 unstoppable" → the distraction montage → the twist →
  the low point → the payoff → a follow CTA.
- **`side-project.meta.json`** — the matching per-platform metadata
  (title / description / hashtags / caption).

## Render it

```bash
# from the repo root (SKILL_DIR = skills/shorts)
python3 skills/shorts/scripts/animate.py --validate skills/shorts/examples/side-project.storyboard.json
python3 skills/shorts/scripts/animate.py skills/shorts/examples/side-project.storyboard.json -o out/side-project.mp4

# or through the orchestrator (also writes a thumbnail + logs to the ledger)
python3 skills/shorts/scripts/pipeline.py build \
    --storyboard skills/shorts/examples/side-project.storyboard.json \
    --meta skills/shorts/examples/side-project.meta.json \
    --out out/side-project.mp4

# then dry-run a publish (add --live + credentials to actually post)
python3 skills/shorts/scripts/publish.py out/side-project.mp4 \
    --meta skills/shorts/examples/side-project.meta.json
```

## What it demonstrates

- **Every pose in a real context:** `idle, talk, run, celebrate, point, think,
  shrug, fall, sit, jump, wave`, plus a second actor entering the frame.
- **Off-screen staging:** the red "reality" actor walks in from `x:1.05`
  (past the right edge) — legal, and how you get entrances/exits.
- **Two actors with distinct colors** sharing a scene (yellow hero + red
  "real life"), with one collapsing as the other arrives.
- **Props as story:** a `ground` line per scene, colored `rect`s standing in
  for the logo / landing page / dark-mode toggle, an empty product box, a
  dimmed "phone" `disk`.
- **Per-scene backgrounds** that carry mood — green for momentum, purple for
  the distraction, near-black for the low point.
- **`title` + `caption`** working together (upper-third hook, lower-third
  narration), auto-wrapped and outlined for legibility on any background.

Copy it, swap the captions/poses for your source video's beat, and you have a
new short. Keep total duration ≤ 60s for Reels/Shorts.
