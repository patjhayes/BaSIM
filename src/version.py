#!/usr/bin/env python3
"""Single source of truth for BaSIM version info and update checks."""

VERSION = "1.2.0"  # Semantic version
BUILD_METADATA = "git:local;built:2026-03-23"
RELEASE_DATE = "2026-03-23"

RELEASE_NOTES = (
	"BaSIM v1.2.0 — Spill warning fix (DEM mode crest), total basin storage reporting, "
	"mean infiltration rate per run, CSV export for stage & flow graphs, "
	"crest line on stage plot, enhanced summary table & HTML report."
)

def check_for_updates(timeout_sec: float = 4.0):
	"""Backward-compatible direct update check (no caching)."""
	try:
		import json, urllib.request
		req = urllib.request.Request(
			"https://api.github.com/repos/basim/basim/releases/latest",
			headers={"User-Agent": "basim-updater"},
		)
		with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
			if resp.status != 200:
				return False, None
			data = json.loads(resp.read().decode("utf-8", errors="ignore"))
		tag = str(data.get("tag_name") or "").lstrip("v").strip()
		if not tag:
			return False, None
		return (tag > VERSION), tag
	except Exception:
		return False, None


def full_version_string() -> str:
	meta = ("+" + BUILD_METADATA) if BUILD_METADATA else ""
	return f"{VERSION}{meta}"


__all__ = [
	"VERSION",
	"BUILD_METADATA",
	"RELEASE_DATE",
	"RELEASE_NOTES",
	"check_for_updates",
	"full_version_string",
]


