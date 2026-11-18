"""Hour-by-hour Twitch viewer quantile forecasts for a big game launch day.

What the program does (competition gta6-twitch-ccu-forecast-01): it reads one
case file per run from the input directory. A case holds a launch day's first
hour count (hour 1, 00:00-01:00 UTC) and the hourly curves of dozens of past
big launches ("comparables"), each spanning 14 days before to 3 days after its
own release day. For every later hour h = 2..24 it writes five quantiles of
that hour's viewer count.

Model, in one paragraph: a launch that is already live around the world at
00:00 UTC (a rolling midnight-local console launch, the profile of this
contest's final and of its practice cases) has a characteristic shape in
log-ratio space, ln(viewers_h / viewers_1). We estimate that shape's
distribution per hour from the comparables whose own release days were
already at scale in hour 1 (their hour-1 count at least 15% of their day's
peak, which keeps out launches whose main unlock came later in the UTC day
and whose hour-1 anchor means something entirely different), weighting each
comparable by how close its hour-1 size is to this case's (a Gaussian kernel
on log size, bandwidth 0.8), and fit a normal per hour: the weighted mean is
the centre, the weighted standard deviation the spread. The forecast is
q_tau(h) = p1 * exp(mu_h + z_tau * sigma_h). Constants (the 15% filter, the
bandwidth, the spread floor and cap) were chosen by leave-one-out backtests
over the comparables themselves, where this scores clearly below the flat
persistence baseline; see FORECAST notes in the repository README.

Runs offline, standard library only, deterministic: the same case always
produces the same bytes.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# Standard-normal quantiles at LEVELS (hard-coded so no lookup can drift).
Z = [-1.644854, -0.674490, 0.0, 0.674490, 1.644854]

# A comparable joins the shape pool when its hour-1 count reached at least
# this share of its release day's peak: its day was already at scale early.
POOL_MIN_HOUR1_SHARE = 0.15
# Gaussian kernel bandwidth on ln(hour-1 viewers) for pool weights.
SIZE_BANDWIDTH = 0.8
# The per-hour log spread is kept inside this band: the floor stops a lucky
# agreement among a few comparables from making the forecast overconfident,
# the cap stops one wild hour from blowing the band open.
SIGMA_FLOOR = 0.12
SIGMA_CAP = 1.20
# The filtered pool is trusted only with at least this many members.
MIN_POOL = 8
# And the size weighting must keep at least this many effective members.
MIN_EFFECTIVE_POOL = 8.0


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def round2(x):
    """Round to 2 decimals, half up; whole numbers come back as int."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if float(value).is_integer() else value


def release_day_curve(comp):
    """{hour 1..24: viewers} of a comparable's UTC release day ({} if unusable)."""
    try:
        start = parse_ts(comp["day_start"])
    except (KeyError, ValueError):
        return {}
    by_hour = {}
    for point in comp.get("hourly") or []:
        viewers = point.get("viewers")
        if viewers is None:
            continue
        try:
            delta = (parse_ts(point["from"]) - start).total_seconds()
        except (KeyError, ValueError):
            continue
        if 0 <= delta < 24 * 3600:
            by_hour[int(delta // 3600) + 1] = viewers
    if not by_hour.get(1):
        return {}
    return by_hour


def shape_pool(case):
    """Day curves of the comparables that can teach this case's shape.

    Two pools are built: every usable curve, and the filtered pool of
    already-at-scale launches. The filtered pool is used when it has enough
    members and this case's own first hour is itself at launch scale (well
    above the category's pre-release level in its history); otherwise the
    full pool is the safer teacher.
    """
    curves = []
    for comp in case.get("comparables") or []:
        curve = release_day_curve(comp)
        if len(curve) >= 12:
            curves.append(curve)
    filtered = []
    for curve in curves:
        peak = max(curve.values())
        if peak > 0 and curve[1] / peak >= POOL_MIN_HOUR1_SHARE:
            filtered.append(curve)
    if len(filtered) >= MIN_POOL and case_is_at_scale(case):
        return filtered
    return curves


def case_is_at_scale(case):
    """True when hour 1 towers over the pre-release level in the history.

    Guards the filtered pool: it describes launches that were already live
    worldwide by 00:00 UTC. If this case's first hour is barely above its own
    pre-release baseline, that profile does not fit and the full pool rules.
    When the history cannot answer, assume the profile fits (the contest's
    cases are rolling midnight-local console launches).
    """
    p1 = hour_one_viewers(case)
    start = parse_ts(case["day_start"])
    pre = []
    for row in case.get("history_hourly") or []:
        try:
            t = parse_ts(row["from"])
        except (KeyError, ValueError):
            continue
        if start - timedelta(hours=48) <= t < start and row.get("viewers"):
            pre.append(row["viewers"])
    if len(pre) < 6:
        return True
    pre.sort()
    median_pre = pre[len(pre) // 2]
    return p1 >= 3.0 * max(median_pre, 1)


def hour_one_viewers(case):
    for row in case.get("known") or []:
        if row.get("hour") == 1 and row.get("viewers") is not None:
            return max(1.0, float(row["viewers"]))
    return 1.0


def weighted_shape(curves, p1):
    """{hour: (mu, sigma)} of ln(viewers_h / viewers_1), size-weighted.

    The kernel bandwidth widens as needed so the weighted pool never
    collapses onto a handful of members: when the case's hour-1 size sits
    outside the pool's size range (a launch bigger than any comparable, say),
    a fixed narrow kernel would rest the whole shape on two or three nearest
    neighbours. The effective member count (sum w)^2 / sum(w^2) is kept at
    or above MIN_EFFECTIVE_POOL by widening the band, up to a sane limit.
    """
    log_p1 = math.log(p1)
    log_sizes = [math.log(curve[1]) for curve in curves]
    bandwidth = SIZE_BANDWIDTH
    weights = []
    for _ in range(8):
        weights = [math.exp(-0.5 * ((ls - log_p1) / bandwidth) ** 2) for ls in log_sizes]
        total = sum(weights)
        effective = total * total / sum(w * w for w in weights)
        if effective >= MIN_EFFECTIVE_POOL:
            break
        bandwidth *= 1.5
    weighted = [(curve, max(w, 1e-6)) for curve, w in zip(curves, weights)]
    shape = {}
    for h in range(2, 25):
        pairs = [(math.log(curve[h] / curve[1]), w)
                 for curve, w in weighted if curve.get(h) and curve[h] > 0]
        if not pairs:
            shape[h] = (0.0, 0.15 * math.sqrt(h - 1))
            continue
        total_w = sum(w for _, w in pairs)
        mu = sum(v * w for v, w in pairs) / total_w
        var = sum(w * (v - mu) ** 2 for v, w in pairs) / total_w
        sigma = min(SIGMA_CAP, max(SIGMA_FLOOR, math.sqrt(var)))
        shape[h] = (mu, sigma)
    return shape


def baseline_shape():
    """The persistence fallback: flat centre, random-walk spread."""
    return {h: (0.0, 0.15 * math.sqrt(h - 1)) for h in range(2, 25)}


def forecast_case(case):
    if list(case.get("levels") or LEVELS) != LEVELS:
        raise ValueError("unexpected levels in case " + str(case.get("id")))
    p1 = hour_one_viewers(case)
    pool = shape_pool(case)
    shape = weighted_shape(pool, p1) if pool else baseline_shape()
    rows = []
    for row in case["forecast"]:
        h = row["hour"]
        mu, sigma = shape[h]
        qs = []
        for z in Z:
            q = p1 * math.exp(mu + z * sigma)
            qs.append(round2(min(1e9, max(0.01, q))))
        # Rounding can in principle break the order; restore it.
        for i in range(1, len(qs)):
            if qs[i] < qs[i - 1]:
                qs[i] = qs[i - 1]
        rows.append({"hour": h, "q": qs})
    return {"hours": rows}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        (OUTPUT_DIR / (path.stem + ".out")).write_text(
            json.dumps(result, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
