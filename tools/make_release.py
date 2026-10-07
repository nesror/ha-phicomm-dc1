#!/usr/bin/env python3
"""Create the GitHub release for a tag, authenticating with the git credential
helper so no token is ever printed or written to disk.

Usage: python tools/make_release.py <tag> <release-notes-file> [--draft]
"""
from __future__ import annotations

import json

import subprocess
import sys
import urllib.error
import urllib.request

REPO = "nesror/ha-phicomm-dc1"


def git_token() -> str:
    """Ask the configured git credential helper for a GitHub secret."""
    proc = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True, text=True, timeout=60, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit("git credential fill failed: " + (proc.stderr or "").strip()[:200])
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            value = line[len("password="):].strip()
            if value:
                return value
    raise SystemExit("no GitHub credential found in the git credential helper")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    tag = sys.argv[1]
    notes_path = sys.argv[2]
    draft = "--draft" in sys.argv

    token = git_token()
    body = open(notes_path, encoding="utf-8").read()

    payload = json.dumps({
        "tag_name": tag,
        "name": f"Phicomm DC1 {tag}",
        "body": body,
        "draft": draft,
        "prerelease": False,
        "target_commitish": "main",
    }).encode()

    request = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/releases",
        data=payload,
        method="POST",
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "phicomm-dc1-release-tool",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = json.loads(response.read())
        print("release created:", data.get("html_url"))
        print("  tag:", data.get("tag_name"), "| draft:", data.get("draft"))
        return 0
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:600]
        print(f"HTTP {err.code}: {detail}")
        if err.code in (401, 403):
            print("凭据不足以创建 release。可以在网页上手工发布：")
            print(f"  https://github.com/{REPO}/releases/new?tag={tag}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
