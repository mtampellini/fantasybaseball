"""
Yahoo fantasy scoring for league 41657 (Il Nuovo Vesuvio).

Pitcher scoring (per scoring.json, fetched 2026-05-11):
    W   = +8.0     Win
    CG  = +10.0    Complete Game
    SHO = +4.0     Shutout
    SV  = +6.0     Save
    QS  = +3.0     Quality Start (>=6 IP, <=3 ER)
    K   = +2.0     Strikeout
    IP  = +0.25    per inning pitched (0.25 / out * 3)
    ER  = -2.0     Earned Run
    BB  = -0.5     Walk allowed

Hitter scoring:
    R    = +1.5    Run scored
    H    = +1.0    Hit (stacks with hit-type bonus below)
    1B   = +1.0    Single
    2B   = +2.0    Double
    3B   = +3.0    Triple
    HR   = +4.0    Home Run
    RBI  = +2.0    Run Batted In
    SB   = +2.0    Stolen Base
    BB   = +1.0    Walk drawn
    CYC  = +15.0   Hitting for the Cycle (modeled in actuals only)
    SLAM = +10.0   Grand Slam (modeled in actuals only)
Net: HR = 1 (H) + 4 (HR) = 5 + R + RBI; 1B = 1 (H) + 1 (1B) = 2.

Notable absences (these stats do NOT score in this league):
    L (losses), H (hits allowed), HBP, HLD, BS, HR allowed, K (batter)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


DEFAULT_SCORING_PATH = Path(__file__).resolve().parents[1] / "data" / "scoring.json"


@dataclass(frozen=True)
class PitcherWeights:
    W: float
    CG: float
    SHO: float
    SV: float
    ER: float
    BB: float
    K: float
    IP: float
    QS: float

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_SCORING_PATH) -> "PitcherWeights":
        data = json.loads(Path(path).read_text())
        m = {s["abbr"]: s["value"] for s in data["pitching"] if s.get("abbr")}
        return cls(
            W=m["W"], CG=m["CG"], SHO=m["SHO"], SV=m["SV"],
            ER=m["ER"], BB=m["BB"], K=m["K"], IP=m["IP"], QS=m["QS"],
        )


def outs_to_ip(outs: int) -> float:
    """Convert recorded outs to decimal innings (e.g., 19 outs -> 6.333)."""
    return outs / 3.0


def pitcher_fp(line: Mapping, w: PitcherWeights | None = None) -> float:
    """
    Compute Yahoo fantasy points for a single pitching appearance.

    Expected line keys (case-insensitive when accessed via line.get):
        outs (int) OR ip (float decimal innings, e.g. 6.333)
        k    (int)  strikeouts
        bb   (int)  walks allowed
        er   (int)  earned runs allowed
        win  (0/1)
        cg   (0/1)
        sho  (0/1)
        sv   (0/1)
        qs   (0/1)  if absent, derived from outs>=18 and er<=3

    Missing keys default to 0. Returns float.
    """
    if w is None:
        w = PitcherWeights.from_file()

    g = lambda k: line.get(k, line.get(k.upper(), line.get(k.lower(), 0))) or 0

    outs = g("outs")
    ip = float(g("ip")) if g("ip") else outs_to_ip(int(outs))

    k_ = int(g("k"))
    bb = int(g("bb"))
    er = int(g("er"))
    win = int(bool(g("win")))
    cg = int(bool(g("cg")))
    sho = int(bool(g("sho")))
    sv = int(bool(g("sv")))

    qs_raw = g("qs")
    if qs_raw == 0 and "qs" not in line and "QS" not in line:
        qs = 1 if (ip >= 6.0 and er <= 3) else 0
    else:
        qs = int(bool(qs_raw))

    pts = (
        ip * w.IP
        + k_ * w.K
        + bb * w.BB
        + er * w.ER
        + win * w.W
        + cg * w.CG
        + sho * w.SHO
        + sv * w.SV
        + qs * w.QS
    )
    return round(pts, 2)


def pitcher_fp_components(line: Mapping, w: PitcherWeights | None = None) -> dict:
    """Same as pitcher_fp but returns per-stat contribution dict."""
    if w is None:
        w = PitcherWeights.from_file()
    g = lambda k: line.get(k, line.get(k.upper(), line.get(k.lower(), 0))) or 0
    outs = int(g("outs"))
    ip = float(g("ip")) if g("ip") else outs_to_ip(outs)
    k_ = int(g("k"))
    bb = int(g("bb"))
    er = int(g("er"))
    win = int(bool(g("win")))
    cg = int(bool(g("cg")))
    sho = int(bool(g("sho")))
    sv = int(bool(g("sv")))
    qs_raw = g("qs")
    if qs_raw == 0 and "qs" not in line and "QS" not in line:
        qs = 1 if (ip >= 6.0 and er <= 3) else 0
    else:
        qs = int(bool(qs_raw))

    comps = {
        "IP": round(ip * w.IP, 2),
        "K":  round(k_ * w.K, 2),
        "BB": round(bb * w.BB, 2),
        "ER": round(er * w.ER, 2),
        "W":  round(win * w.W, 2),
        "CG": round(cg * w.CG, 2),
        "SHO": round(sho * w.SHO, 2),
        "SV": round(sv * w.SV, 2),
        "QS": round(qs * w.QS, 2),
    }
    comps["total"] = round(sum(comps.values()), 2)
    return comps


@dataclass(frozen=True)
class HitterWeights:
    R: float
    H: float
    B1: float   # single
    B2: float   # double
    B3: float   # triple
    HR: float
    RBI: float
    SB: float
    BB: float
    CYC: float
    SLAM: float

    @classmethod
    def from_file(cls, path: Path | str = DEFAULT_SCORING_PATH) -> "HitterWeights":
        data = json.loads(Path(path).read_text())
        m = {s["abbr"]: s["value"] for s in data["batting"] if s.get("abbr")}
        return cls(
            R=m["R"], H=m["H"], B1=m["1B"], B2=m["2B"], B3=m["3B"], HR=m["HR"],
            RBI=m["RBI"], SB=m["SB"], BB=m["BB"],
            CYC=m.get("CYC", 0.0), SLAM=m.get("SLAM", 0.0),
        )


def hitter_fp(line: Mapping, w: HitterWeights | None = None,
              include_bonuses: bool = True) -> float:
    """
    Compute Yahoo fantasy points for a single batting line (one game).

    Expected line keys (case-insensitive lookup):
        h   (int)  hits
        2b  (int)  doubles
        3b  (int)  triples
        hr  (int)  home runs
        r   (int)  runs scored
        rbi (int)  runs batted in
        bb  (int)  walks
        sb  (int)  stolen bases
        cyc (0/1)  hit for the cycle (optional)
        slam(int)  grand slams hit (optional)

    Singles are derived: 1B = H - 2B - 3B - HR.

    include_bonuses: keep CYC/SLAM in the score. Set False when computing
    the model target (FP/G) to avoid fitting rare-event noise.
    """
    if w is None:
        w = HitterWeights.from_file()

    g = lambda k: line.get(k, line.get(k.upper(), line.get(k.lower(), 0))) or 0

    h = int(g("h"))
    b2 = int(g("2b"))
    b3 = int(g("3b"))
    hr = int(g("hr"))
    b1 = max(0, h - b2 - b3 - hr)
    r = int(g("r"))
    rbi = int(g("rbi"))
    bb = int(g("bb"))
    sb = int(g("sb"))

    pts = (
        r * w.R
        + h * w.H
        + b1 * w.B1
        + b2 * w.B2
        + b3 * w.B3
        + hr * w.HR
        + rbi * w.RBI
        + sb * w.SB
        + bb * w.BB
    )

    if include_bonuses:
        cyc = int(bool(g("cyc")))
        slam = int(g("slam"))
        pts += cyc * w.CYC + slam * w.SLAM

    return round(pts, 2)


def hitter_fp_components(line: Mapping, w: HitterWeights | None = None,
                         include_bonuses: bool = True) -> dict:
    """Same as hitter_fp but returns per-stat contribution dict."""
    if w is None:
        w = HitterWeights.from_file()
    g = lambda k: line.get(k, line.get(k.upper(), line.get(k.lower(), 0))) or 0
    h = int(g("h"))
    b2 = int(g("2b"))
    b3 = int(g("3b"))
    hr = int(g("hr"))
    b1 = max(0, h - b2 - b3 - hr)
    r = int(g("r"))
    rbi = int(g("rbi"))
    bb = int(g("bb"))
    sb = int(g("sb"))
    cyc = int(bool(g("cyc")))
    slam = int(g("slam"))

    comps = {
        "R":   round(r * w.R, 2),
        "H":   round(h * w.H, 2),
        "1B":  round(b1 * w.B1, 2),
        "2B":  round(b2 * w.B2, 2),
        "3B":  round(b3 * w.B3, 2),
        "HR":  round(hr * w.HR, 2),
        "RBI": round(rbi * w.RBI, 2),
        "SB":  round(sb * w.SB, 2),
        "BB":  round(bb * w.BB, 2),
    }
    if include_bonuses:
        comps["CYC"] = round(cyc * w.CYC, 2)
        comps["SLAM"] = round(slam * w.SLAM, 2)
    comps["total"] = round(sum(comps.values()), 2)
    return comps


if __name__ == "__main__":
    w = PitcherWeights.from_file()
    print(f"Loaded weights: {w}\n")

    cases = [
        ("Skubal 8 IP CG W 12K 0 ER 1 BB",
         {"outs": 24, "k": 12, "bb": 1, "er": 0, "win": 1, "cg": 1, "sho": 1}),
        ("Typical QS: 6 IP 7K 2 ER 2 BB W",
         {"outs": 18, "k": 7, "bb": 2, "er": 2, "win": 1}),
        ("Blow-up: 4.1 IP 3K 5 ER 3 BB L",
         {"outs": 13, "k": 3, "bb": 3, "er": 5}),
        ("Solid no-decision: 5.2 IP 6K 1 ER 0 BB",
         {"outs": 17, "k": 6, "bb": 0, "er": 1}),
    ]
    for name, line in cases:
        comps = pitcher_fp_components(line, w)
        print(f"{name}")
        print(f"  components: {comps}")
        print(f"  TOTAL FP : {comps['total']}\n")

    hw = HitterWeights.from_file()
    print(f"Hitter weights: {hw}\n")
    hcases = [
        ("Solo HR + walk: 4 AB 1 H 1 HR 1 R 1 RBI 1 BB",
         {"h": 1, "2b": 0, "3b": 0, "hr": 1, "r": 1, "rbi": 1, "bb": 1, "sb": 0}),
         # Expected: R 1.5 + H 1 + HR 4 + RBI 2 + BB 1 = 9.5
        ("3-for-4 with 2B and SB: 4 AB 3 H 1 2B 2 R 1 RBI 0 BB 1 SB",
         {"h": 3, "2b": 1, "3b": 0, "hr": 0, "r": 2, "rbi": 1, "bb": 0, "sb": 1}),
         # Expected: R 3.0 + H 3 + 1B (2*1) + 2B 2 + RBI 2 + SB 2 = 14.0
        ("Walk-only: 3 AB 0 H 0 R 0 RBI 1 BB",
         {"h": 0, "2b": 0, "3b": 0, "hr": 0, "r": 0, "rbi": 0, "bb": 1, "sb": 0}),
         # Expected: BB 1 = 1.0
        ("Grand slam: 4 AB 1 H 1 HR 1 R 4 RBI 0 BB SLAM",
         {"h": 1, "2b": 0, "3b": 0, "hr": 1, "r": 1, "rbi": 4, "bb": 0, "sb": 0,
          "slam": 1}),
         # Expected (with bonus): R 1.5 + H 1 + HR 4 + RBI 8 + SLAM 10 = 24.5
    ]
    for name, line in hcases:
        comps = hitter_fp_components(line, hw)
        print(f"{name}")
        print(f"  components: {comps}")
        print(f"  TOTAL FP : {comps['total']}\n")
