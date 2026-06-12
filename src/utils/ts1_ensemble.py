"""TS1 Ensemble Grouping Utility.

Parses TS1 filenames to extract AEP, duration and temporal-pattern tokens,
then groups files into ensembles (same AEP + duration) and selects the
median member by peak stage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Token extraction (mirrors _short_ts1._extract_tokens in the engine)
# ---------------------------------------------------------------------------

def extract_storm_tokens(text: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (aep, duration, tp) tokens from a text string.

    Handles RORB-style compound names like ``aep6EY_du1hourtp21`` as well
    as general patterns with clear word boundaries.

    Examples
    --------
    >>> extract_storm_tokens("test_ aep1_du1hourtp21.out.ts1")
    ('1pct', '1h', 'TP21')
    >>> extract_storm_tokens("test_ aep6EY_du45min.out.ts1")
    ('6EY', '45m', None)
    """
    s1 = s2 = s3 = None
    t_sp = re.sub(r"[_,]+", " ", text or "")

    # ── AEP ────────────────────────────────────────────────
    # Exact <N>% AEP match (e.g. 1% AEP) to prevent adjacent numbers from being misidentified
    m = re.search(r'\b(\d+)\s*%\s*aep\b', t_sp, re.I)
    if m:
        s1 = f"{m.group(1)}pct"
    
    if not s1:
        # RORB-style: aep<N>EY  (e.g. aep6EY)
        m = re.search(r'aep\s*(\d+)\s*EY', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}EY"

    if not s1:
        # RORB-style: aep<N> with % sign (e.g. aep1%)
        m = re.search(r'aep\s*(\d+)\s*%', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}pct"

    if not s1:
        # RORB-style: aep<N> (plain percentage, e.g. aep1 → 1%)
        m = re.search(r'aep\s*(\d+)(?=\s|[^A-Za-z0-9]|$)', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}pct"
    # General patterns (if RORB-specific didn't match)
    if not s1:
        m = re.search(r'\b(\d+)\s*%\b', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}pct"
    if not s1:
        m = re.search(r'\b(\d+)\s*p(?:c|ct)\b', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}pct"
    if not s1:
        m = re.search(r'\b(\d+)\s*ey\b', t_sp, re.I)
        if m:
            s1 = f"{m.group(1)}EY"
    if not s1:
        m = re.search(r'\b1\s*in\s*(\d+)\b', t_sp, re.I)
        if m:
            s1 = f"1in{m.group(1)}"
    if not s1:
        m = re.search(r'\bari\s*(\d+)\s*(?:yr|year|years)?\b', t_sp, re.I)
        if m:
            s1 = f"1in{m.group(1)}"
    if not s1:
        m = re.search(r'\b(\d+)\s*(?:yr|year|years)\s*ari\b', t_sp, re.I)
        if m:
            s1 = f"1in{m.group(1)}"

    # ── Duration ───────────────────────────────────────────
    # RORB du-prefix: du<N>[_<N>]<unit>  (e.g. du1hour, du4_5hour, du45min)
    m = re.search(r'du\s*(\d+(?:\s+\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|m|days?|d)',
                  t_sp, re.I)
    if m:
        val = m.group(1).replace(' ', '_')  # e.g. "4 5" → "4_5"
        unit = m.group(2)[0].lower()
        s2 = f"{val}{unit}"
    # General patterns (no du- prefix)
    if not s2:
        m = re.search(r'\b(\d+)\s*h(?:our|r|rs)?s?\b', t_sp, re.I)
        if m:
            s2 = f"{m.group(1)}h"
    if not s2:
        m = re.search(r'\b(\d+)\s*m(?:in(?:ute)?s?)?\b', t_sp, re.I)
        if m:
            s2 = f"{m.group(1)}m"
    if not s2:
        m = re.search(r'\b(\d+)\s*d(?:ay)?s?\b', t_sp, re.I)
        if m:
            s2 = f"{m.group(1)}d"

    # ── Temporal Pattern ───────────────────────────────────
    # tp<N> anywhere (even concatenated like hourtp21)
    m = re.search(r'tp\s*0*(\d+)', t_sp, re.I)
    if m:
        s3 = f"TP{int(m.group(1))}"
    else:
        m = re.search(r'\bstorm\s*0*(\d+)\b', t_sp, re.I)
        if m:
            s3 = f"TP{int(m.group(1))}"

    return s1, s2, s3


def extract_storm_tokens_from_file(filepath: str | Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract tokens from filename, falling back to file header and parent folders."""
    p = Path(filepath)
    s1, s2, s3 = extract_storm_tokens(p.stem)

    # Fallback: scan file header lines
    if not (s1 and s2):
        try:
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                for _ in range(10):
                    ln = f.readline()
                    if not ln:
                        break
                    h1, h2, h3 = extract_storm_tokens(ln.strip())
                    s1 = s1 or h1
                    s2 = s2 or h2
                    s3 = s3 or h3
                    if s1 and s2 and s3:
                        break
        except Exception:
            pass

    # Fallback: parent folder names
    if not s1:
        try:
            for part in reversed(p.parts[-5:]):
                f1, _, f3 = extract_storm_tokens(part)
                if f1:
                    s1 = f1
                    s3 = s3 or f3
                    break
        except Exception:
            pass

    return s1, s2, s3


# ---------------------------------------------------------------------------
# Ensemble data structures
# ---------------------------------------------------------------------------

@dataclass
class StormMember:
    """One TS1 member within an ensemble."""
    filepath: str
    aep: Optional[str] = None
    duration: Optional[str] = None
    tp: Optional[str] = None
    peak_stage: Optional[float] = None  # populated after runs complete


@dataclass
class StormEnsemble:
    """A group of TP variants sharing the same AEP + duration."""
    aep: str
    duration: str
    members: List[StormMember] = field(default_factory=list)
    median_index: Optional[int] = None  # index into members of median peak-stage member

    @property
    def key(self) -> str:
        return f"{self.aep}_{self.duration}"

    @property
    def median_member(self) -> Optional[StormMember]:
        if self.median_index is not None and 0 <= self.median_index < len(self.members):
            return self.members[self.median_index]
        return None


# ---------------------------------------------------------------------------
# Grouping / median selection
# ---------------------------------------------------------------------------

def group_ts1_files(filepaths: List[str]) -> Tuple[List[StormEnsemble], List[StormMember]]:
    """Group TS1 files by (AEP, duration).

    Returns
    -------
    ensembles : list of StormEnsemble
        Groups with at least 2 members (or 1 member with fully-parsed tokens).
    ungrouped : list of StormMember
        Files that could not be assigned to any ensemble.
    """
    members: List[StormMember] = []
    for fp in filepaths:
        aep, dur, tp = extract_storm_tokens_from_file(fp)
        members.append(StormMember(filepath=fp, aep=aep, duration=dur, tp=tp))

    # Build groups by (aep, duration)
    groups: Dict[str, List[StormMember]] = {}
    ungrouped: List[StormMember] = []
    for m in members:
        if m.aep and m.duration:
            key = f"{m.aep}_{m.duration}"
            groups.setdefault(key, []).append(m)
        else:
            ungrouped.append(m)

    ensembles = []
    for key, grp in groups.items():
        aep = grp[0].aep
        dur = grp[0].duration
        ensembles.append(StormEnsemble(aep=aep, duration=dur, members=grp))

    # Sort ensembles by AEP rarity then duration
    ensembles.sort(key=lambda e: (_aep_sort_key(e.aep), _dur_to_hours(e.duration)))

    return ensembles, ungrouped


def select_median_by_peak_stage(ensemble: StormEnsemble) -> Optional[int]:
    """Find the member closest to the median peak stage.

    Requires that ``peak_stage`` has been populated on each member.
    Returns the index into ``ensemble.members`` (also sets
    ``ensemble.median_index``).
    """
    stages = [(i, m.peak_stage) for i, m in enumerate(ensemble.members) if m.peak_stage is not None]
    if not stages:
        return None

    stages.sort(key=lambda x: x[1])
    median_pos = len(stages) // 2  # upper-median for even counts
    idx = stages[median_pos][0]
    ensemble.median_index = idx
    return idx


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _aep_sort_key(aep: str) -> float:
    """Convert AEP string to a numeric value for sorting (rarer → higher)."""
    if not aep:
        return 999.0
    m = re.match(r"(\d+)pct", aep, re.I)
    if m:
        return 100 - float(m.group(1))  # 1pct → 99 (rarer), 50pct → 50
    m = re.match(r"(\d+)EY", aep, re.I)
    if m:
        return -float(m.group(1))  # frequent events: 6EY → -6, 12EY → -12
    m = re.match(r"1in(\d+)", aep, re.I)
    if m:
        return 100 - (100 / float(m.group(1)))  # 1in100 → 99
    return 500.0  # unknown


def _dur_to_hours(dur: str) -> float:
    """Convert duration string to hours for sorting."""
    if not dur:
        return 999.0
    m = re.match(r"(\d+)([hmd])", dur, re.I)
    if not m:
        return 999.0
    val = float(m.group(1))
    unit = m.group(2).lower()
    if unit == "h":
        return val
    elif unit == "m":
        return val / 60.0
    elif unit == "d":
        return val * 24.0
    return val


def ensemble_label(ens: StormEnsemble) -> str:
    """Human-readable label for an ensemble, e.g. '1% AEP 1h (10 TPs)'."""
    aep_nice = _format_aep(ens.aep)
    return f"{aep_nice} {ens.duration} ({len(ens.members)} TPs)"


def _format_aep(aep: str) -> str:
    """Pretty-print AEP token."""
    if not aep:
        return "?"
    m = re.match(r"(\d+)pct", aep, re.I)
    if m:
        return f"{m.group(1)}% AEP"
    m = re.match(r"(\d+)EY", aep, re.I)
    if m:
        return f"{m.group(1)} EY"
    m = re.match(r"1in(\d+)", aep, re.I)
    if m:
        return f"1 in {m.group(1)}"
    return aep
