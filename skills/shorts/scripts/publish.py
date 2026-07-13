#!/usr/bin/env python3
"""Publish a finished short to YouTube, Instagram, and Facebook.

Design rules (deliberate, do not "helpfully" remove):
  * DRY-RUN BY DEFAULT. A live post only happens with `--live`, and only when
    the matching credentials are present. There is no path where a short goes
    public without an explicit human/agent decision on that specific run.
  * Credentials come from ~/.config/shorts/.env and are never printed.
  * Pure stdlib (urllib). Each platform is an isolated adapter so a missing
    credential for one never blocks the others.

Credentials expected in ~/.config/shorts/.env:
  YouTube (Data API v3, OAuth):   YT_ACCESS_TOKEN
  Instagram (Graph API, Reels):   IG_USER_ID, IG_ACCESS_TOKEN  (+ public video URL)
  Facebook (Graph API, Reels):    FB_PAGE_ID, FB_ACCESS_TOKEN

Instagram/Facebook Reels require a publicly reachable video URL (the Graph API
pulls the file itself); host the MP4 somewhere public and pass --video-url.

Usage:
    python3 publish.py short.mp4 --meta meta.json                 # dry-run all
    python3 publish.py short.mp4 --meta meta.json --platform youtube --live
    python3 publish.py short.mp4 --meta meta.json --platform instagram \
        --video-url https://cdn.example.com/short.mp4 --live
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from shorts_config import get  # noqa: E402

PLATFORMS = ("youtube", "instagram", "facebook")


def _http(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None) -> dict:
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        return json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return {"raw": raw}


# --------------------------------------------------------------------------- #
# YouTube (resumable upload, Data API v3)
# --------------------------------------------------------------------------- #


def publish_youtube(video: str, meta: dict, live: bool) -> dict:
    token = get("YT_ACCESS_TOKEN")
    title = meta.get("title", "Untitled Short")
    description = meta.get("description", "")
    tags = meta.get("tags", meta.get("hashtags", []))
    if not token:
        return {"platform": "youtube", "status": "skipped", "reason": "YT_ACCESS_TOKEN not set"}
    if not live:
        return {"platform": "youtube", "status": "dry-run", "would_upload": video,
                "title": title, "tags": tags}

    body = Path(video).read_bytes()
    snippet = {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "24"},
        "status": {"privacyStatus": meta.get("privacy", "private"), "selfDeclaredMadeForKids": False},
    }
    init = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(snippet).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/*",
            "X-Upload-Content-Length": str(len(body)),
        },
        method="POST",
    )
    with urllib.request.urlopen(init, timeout=60) as resp:
        upload_url = resp.headers.get("Location")
    if not upload_url:
        return {"platform": "youtube", "status": "error", "reason": "no resumable upload URL returned"}
    up = urllib.request.Request(
        upload_url, data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "video/*", "Content-Length": str(len(body))},
        method="PUT",
    )
    with urllib.request.urlopen(up, timeout=600) as resp:
        result = json.loads(resp.read().decode("utf-8", "replace"))
    vid = result.get("id")
    return {"platform": "youtube", "status": "published", "id": vid,
            "url": f"https://youtu.be/{vid}" if vid else None}


# --------------------------------------------------------------------------- #
# Instagram Reels (Graph API, container -> publish)
# --------------------------------------------------------------------------- #


def publish_instagram(video: str, meta: dict, live: bool, video_url: str | None) -> dict:
    ig_user = get("IG_USER_ID")
    token = get("IG_ACCESS_TOKEN")
    caption = meta.get("caption") or _compose_caption(meta)
    if not (ig_user and token):
        return {"platform": "instagram", "status": "skipped", "reason": "IG_USER_ID / IG_ACCESS_TOKEN not set"}
    if not video_url:
        return {"platform": "instagram", "status": "skipped",
                "reason": "Instagram pulls the file itself — pass --video-url (public MP4 URL)"}
    if not live:
        return {"platform": "instagram", "status": "dry-run", "video_url": video_url, "caption": caption}

    base = f"https://graph.facebook.com/v19.0/{ig_user}"
    create = _http(
        f"{base}/media",
        data=urllib.parse.urlencode({
            "media_type": "REELS", "video_url": video_url, "caption": caption, "access_token": token,
        }).encode(),
        method="POST",
    )
    container = create.get("id")
    if not container:
        return {"platform": "instagram", "status": "error", "reason": create}
    # Poll until the container finishes processing.
    for _ in range(30):
        status = _http(f"https://graph.facebook.com/v19.0/{container}?fields=status_code&access_token={token}")
        if status.get("status_code") == "FINISHED":
            break
        if status.get("status_code") == "ERROR":
            return {"platform": "instagram", "status": "error", "reason": status}
        time.sleep(5)
    published = _http(
        f"{base}/media_publish",
        data=urllib.parse.urlencode({"creation_id": container, "access_token": token}).encode(),
        method="POST",
    )
    return {"platform": "instagram", "status": "published", "id": published.get("id")}


# --------------------------------------------------------------------------- #
# Facebook Reels (Graph API)
# --------------------------------------------------------------------------- #


def publish_facebook(video: str, meta: dict, live: bool, video_url: str | None) -> dict:
    page = get("FB_PAGE_ID")
    token = get("FB_ACCESS_TOKEN")
    description = meta.get("caption") or _compose_caption(meta)
    if not (page and token):
        return {"platform": "facebook", "status": "skipped", "reason": "FB_PAGE_ID / FB_ACCESS_TOKEN not set"}
    if not video_url:
        return {"platform": "facebook", "status": "skipped",
                "reason": "Facebook Reels needs a public --video-url"}
    if not live:
        return {"platform": "facebook", "status": "dry-run", "video_url": video_url, "description": description}

    start = _http(
        f"https://graph.facebook.com/v19.0/{page}/video_reels",
        data=urllib.parse.urlencode({"upload_phase": "start", "access_token": token}).encode(),
        method="POST",
    )
    video_id = start.get("video_id")
    if not video_id:
        return {"platform": "facebook", "status": "error", "reason": start}
    finish = _http(
        f"https://graph.facebook.com/v19.0/{page}/video_reels",
        data=urllib.parse.urlencode({
            "upload_phase": "finish", "video_id": video_id, "video_url": video_url,
            "description": description, "access_token": token,
        }).encode(),
        method="POST",
    )
    return {"platform": "facebook", "status": "published", "id": video_id, "result": finish}


def _compose_caption(meta: dict) -> str:
    parts = [meta.get("title", "")]
    if meta.get("description"):
        parts.append(meta["description"])
    tags = meta.get("hashtags") or meta.get("tags") or []
    if tags:
        parts.append(" ".join(t if t.startswith("#") else f"#{t}" for t in tags))
    return "\n\n".join(p for p in parts if p).strip()


def main() -> int:
    ap = argparse.ArgumentParser(prog="publish", description="Publish a short (dry-run unless --live).")
    ap.add_argument("video", help="Path to the rendered MP4")
    ap.add_argument("--meta", required=True, help="Path to metadata JSON (title/description/hashtags/caption)")
    ap.add_argument("--platform", choices=[*PLATFORMS, "all"], default="all")
    ap.add_argument("--video-url", default=None, help="Public URL of the MP4 (required for IG/FB)")
    ap.add_argument("--live", action="store_true", help="Actually post. Without this, dry-run.")
    args = ap.parse_args()

    meta = json.loads(Path(args.meta).read_text(encoding="utf-8"))
    targets = PLATFORMS if args.platform == "all" else (args.platform,)

    results = []
    for platform in targets:
        if platform == "youtube":
            results.append(publish_youtube(args.video, meta, args.live))
        elif platform == "instagram":
            results.append(publish_instagram(args.video, meta, args.live, args.video_url))
        elif platform == "facebook":
            results.append(publish_facebook(args.video, meta, args.live, args.video_url))

    print(json.dumps({"live": args.live, "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
