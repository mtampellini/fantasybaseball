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

Notable absences (these stats do NOT score in this league):
    L (losses), H (hits allowed), HBP, HLD, BS, HR allowed
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
