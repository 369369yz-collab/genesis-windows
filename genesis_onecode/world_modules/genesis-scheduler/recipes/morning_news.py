#!/usr/bin/env python3
"""morning_news runner: fetch top headlines from a free public RSS feed and
save a dated Markdown digest. Invoked by the genesis-scheduler morning_news
recipe via schtasks on Windows (or manually anywhere).

Zero spend. Real HTTP fetch with urllib (stdlib). On fetch failure it exits 1
with an honest error -- it never invents headlines.
"""
import argparse
import html
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

FEED_URL = "https://feeds.bbci.co.uk/news/rss.xml"
MAX_ITEMS = 10
TIMEOUT_S = 20


def fetch_headlines(feed_url=FEED_URL, max_items=MAX_ITEMS):
    req = urllib.request.Request(
        feed_url, headers={"User-Agent": "genesis-scheduler/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        raw = resp.read()
    root = ET.fromstring(raw)
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        if title:
            items.append({"title": html.unescape(title),
                          "link": link, "published": pub})
        if len(items) >= max_items:
            break
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GENESIS morning news digest")
    ap.add_argument("--out-dir", required=True,
                    help="directory for the dated digest file")
    ap.add_argument("--feed-url", default=FEED_URL)
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_file = out_dir / ("news-%s.md" % stamp)

    try:
        items = fetch_headlines(args.feed_url)
    except Exception as exc:
        err = {"status": "error",
               "reason": "headline fetch failed: %s: %s"
                         % (type(exc).__name__, exc)}
        print(json.dumps(err))
        (out_dir / ("news-%s.error.json" % stamp)).write_text(
            json.dumps(err, indent=2), encoding="utf-8")
        return 1

    lines = ["# Morning News -- %s" % stamp, ""]
    for i, it in enumerate(items, 1):
        lines.append("%d. **%s**" % (i, it["title"]))
        if it["link"]:
            lines.append("   %s" % it["link"])
    lines += ["", "_Source: %s | generated %s_" %
              (args.feed_url, datetime.now(timezone.utc).isoformat())]
    out_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"status": "ok", "items": len(items),
                      "file": str(out_file)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
