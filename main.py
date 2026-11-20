"""Forecast GTA VI trophy earn rates on Exophase, one week after launch.

Competition: gta6-trophy-rarity-forecast-01. One run per case: read
<input>/<id>.in (schema makefun/gta6-trophies-case/v1) and write
<output>/<id>.out as {"trophies": [{"id": n, "q": [q05, q25, q50, q75, q95]}]}
for every trophy in the case. Python 3.13, standard library only, no
network, deterministic.

What the data is
---------------
A trophy's earn rate is the share of the players Exophase tracks for the
game who hold it. Exophase refreshes a game's counts on its own schedule,
hours apart, not continuously: the page sits unchanged between refreshes,
then jumps. A refresh does two things at once: the tracked-player count N
grows (new players syncing their profiles), which *dilutes* every rate,
and the holders H grow as the existing players progress. So a rate's move
is the net of progression (up) and dilution (down), and consecutive
identical reads carry no new information at all.

Method
------
1. Collapse the history to distinct reads (a new players_tracked or a
   changed rate vector). Between refreshes nothing moves, so identical
   reads are dropped before any fitting.

2. Per trophy, fit a line of logit(rate) on x = ln(1 + hours since
   release), by recency-weighted least squares (half-weight per 12 hours
   of age: launch-night dynamics are not day-two dynamics, and the most
   recent day's slope is the best guide to the next days). The forecast
   anchors on the trophy's last observed rate and extrapolates only the
   *change*: logit(r_target) = logit(r_last) + b * (x_target - x_last),
   with the logit change clamped to [-3.5, +3.5] as a guard against wild
   extrapolation. The log-time transform is the saturation: growth in
   logit space slows as the game ages, so early story trophies can climb
   a long way while the platinum barely moves.

3. Shrinkage. A trophy's own slope is shrunk toward the median slope of
   its tier (platinum / gold / silver / bronze trophies move together:
   story bronzes climb fast, the platinum crawls). Weight on the own
   slope is n / (n + 4) in distinct reads, so a two-point fit barely
   counts and a long history speaks for itself. Trophies with no usable
   fit take their tier median; with no tier median, the global median.

4. Flat history (fewer than 2 distinct reads) means the page has not
   refreshed since the first read: the next refresh will reveal all the
   player growth accumulated since then. The forecast then uses a
   refresh catch-up prior instead of a trend: tracked players grow at
   ~0.39/hour early after launch (the first published refresh took the
   count 638 -> 3,868 over ~4.7 hours, i.e. ln(6.06)/4.7), decaying with
   a 24-hour time constant as the launch cohort saturates, and newcomers
   hold each trophy at a marginal rate that is tiny except for the
   earliest trophies (weights proportional to the square of the current
   rate; a trophy everyone holds stays held). The median rate is the
   diluted mixture (r + (g - 1) * m) / g, with a wide spread.

5. Spread. The logit spread combines the trophy's own fit residual, its
   slope uncertainty times the extrapolation distance, cross-trophy
   slope disagreement, and a horizon term 0.35 * sqrt(days) for
   refreshes and model error the history cannot see. Floored at 0.45,
   capped at 2.2 logits. Quantiles are the normal quantiles at the
   case's levels around the median in logit space, rounded half-up to
   4 decimals, clamped to [0.01, 100] and forced non-decreasing.

6. A trophy at (essentially) 100% stays there: its quantiles are
   [99.5, 99.9, 100, 100, 100]. Every tracked player holds it, and the
   one refresh the house ever published left it at 100% through a 6x
   growth in tracked players.

Why this beats the house persistence baseline: persistence assumes the
rates stand still, but over a week they do not -- the practice cases
straddle Exophase's first refresh, where every rate but the 100% one
fell as the tracked count grew 6x, and the baseline's narrow band
covers none of it (published practice loss ~1.51, coverage 0). This
forecaster expects the refresh (flat history -> dilution prior) and,
on a real history, extrapolates each trophy's own trend with a spread
calibrated from how much trophies actually disagree.

Robustness: every optional field is treated as optional. Missing or
empty history falls back to a 1% median with a wide spread. Nothing
reads the clock, the network, or any randomness, so two runs on the
same input produce byte-identical output.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SRC_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
DST_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z = [-1.6448536269514722, -0.6744897501960817, 0.0,
     0.6744897501960817, 1.6448536269514722]

RELEASE_HOUR0 = datetime(2026, 11, 19, tzinfo=timezone.utc)
MAX_LOGIT_MOVE = 3.5
SPREAD_FLOOR = 0.45
SPREAD_CAP = 2.2
# Prior: tracked players grow ~0.39/hour just after launch, decaying with
# a 24 h time constant (see module docstring, point 4).
GROWTH_RATE0 = 0.39
GROWTH_DECAY_HOURS = 24.0
GROWTH_CAP = 8.0
# Prior: a fresh player holds on average this many non-ubiquitous
# trophies (they have barely started; the launch-night cohort holds
# ~0.48 each beyond the one trophy everyone has).
NEWCOMER_TROPHIES = 0.15


def _parse_instant(text):
    if not isinstance(text, str):
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


def _clamp_pct(x):
    return min(99.99, max(0.01, x))


def _logit(pct):
    p = _clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def _inv_logit(value):
    if value >= 0:
        return 100.0 / (1.0 + math.exp(-value))
    odds = math.exp(value)
    return 100.0 * odds / (1.0 + odds)


def _round_half_up_4dp(value):
    scaled = value * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    result = whole / 10000.0
    return int(result) if float(result).is_integer() else result


def _median(values):
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return 0.5 * (ordered[middle - 1] + ordered[middle])


def _release_start(case):
    game = case.get("game") or {}
    raw = game.get("release_date")
    if isinstance(raw, str):
        moment = _parse_instant(raw + "T00:00:00Z" if len(raw) == 10 else raw)
        if moment is not None:
            return moment
    history = case.get("history") or []
    if history:
        first = _parse_instant(history[0].get("at"))
        if first is not None:
            return first
    return RELEASE_HOUR0


def _hours_since(start, moment):
    return max(0.0, (moment - start).total_seconds() / 3600.0)


def _log_time(hours):
    return math.log1p(hours)


def _distinct_reads(case, start):
    """History collapsed to reads that changed something, oldest first.

    Each entry: (hours since release, players_tracked, rates list).
    A read whose players count and whole rate vector equal the previous
    distinct read is the same frozen page and carries no information.
    """
    distinct = []
    previous_key = None
    for read in case.get("history") or []:
        if not isinstance(read, dict):
            continue
        moment = _parse_instant(read.get("at"))
        if moment is None:
            continue
        rates = read.get("rates") or []
        players = read.get("players_tracked")
        key = (players, tuple(rates))
        if key == previous_key:
            continue
        previous_key = key
        distinct.append((_hours_since(start, moment), players, rates))
    return distinct


def _weighted_line(points):
    """Recency-weighted least squares of y on x.

    points: list of (x, y, weight). Returns (slope, intercept, resid_sd,
    slope_se), with the last two None when they cannot be estimated, or
    None when fewer than 2 points, no x variation, or the points span
    too little log-time for a slope to mean anything (two reads seconds
    apart would otherwise give an exploding slope).
    """
    if len(points) < 2:
        return None
    xs = [x for x, _, _ in points]
    if max(xs) - min(xs) < 0.1:
        return None
    total_w = sum(w for _, _, w in points)
    mean_x = sum(w * x for x, _, w in points) / total_w
    mean_y = sum(w * y for _, y, w in points) / total_w
    sxx = sum(w * (x - mean_x) ** 2 for x, _, w in points)
    if sxx <= 0:
        return None
    sxy = sum(w * (x - mean_x) * (y - mean_y) for x, y, w in points)
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    if len(points) >= 3:
        resid_var = sum(w * (y - (intercept + slope * x)) ** 2
                        for x, y, w in points) / total_w
        resid_var *= len(points) / max(1, len(points) - 2)
        resid_sd = math.sqrt(max(0.0, resid_var))
        slope_se = math.sqrt(max(0.0, resid_var) / sxx)
    else:
        resid_sd = None
        slope_se = None
    return slope, intercept, resid_sd, slope_se


def _trophy_points(distinct, index):
    """Weighted (log-time, logit rate, weight) points for one trophy.

    Skips reads that lack the trophy and rates at/above 99.5% (a rate
    pinned at the top carries no slope information). Weights halve per
    12 hours of age against the last distinct read.
    """
    raw = []
    for hours, _players, rates in distinct:
        if index >= len(rates):
            continue
        rate = rates[index]
        if not isinstance(rate, (int, float)):
            continue
        if rate >= 99.5 or rate <= 0.0:
            continue
        raw.append((hours, _logit(rate)))
    if len(raw) < 2:
        return raw, []
    last_hours = raw[-1][0]
    points = [(_log_time(hours), y, 0.5 ** (max(0.0, last_hours - hours) / 12.0))
              for hours, y in raw]
    return raw, points


def _last_rate(distinct, index):
    """The trophy's rate in the last distinct read that has one."""
    for _hours, _players, rates in reversed(distinct):
        if index < len(rates) and isinstance(rates[index], (int, float)):
            return float(rates[index])
    return None


def _refresh_growth(first_hours, target_hours):
    """Prior growth factor of tracked players between two instants.

    Growth runs at GROWTH_RATE0 per hour just after launch and decays
    with a 24-hour time constant; the factor is the integral of that
    rate over the window, capped.
    """
    if target_hours <= first_hours:
        return 1.0
    integral = (GROWTH_RATE0 * GROWTH_DECAY_HOURS
                * (math.exp(-first_hours / GROWTH_DECAY_HOURS)
                   - math.exp(-target_hours / GROWTH_DECAY_HOURS)))
    return min(GROWTH_CAP, math.exp(integral)) if integral > 0 else 1.0


def _monotone(values):
    """Force a quantile row non-decreasing, keeping it in [0.01, 100]."""
    out = []
    previous = 0.0
    for value in values:
        value = min(100.0, max(0.01, value))
        if value <= previous:
            value = min(100.0, _round_half_up_4dp(previous + 0.0001))
            if value <= previous:
                value = previous
        out.append(value)
        previous = value
    return out


def _quantile_row(centre, spread, z_values):
    row = [_round_half_up_4dp(min(100.0, max(0.01, _inv_logit(centre + z * spread))))
           for z in z_values]
    return _monotone(row)


def _forecast_flat(last_rates, growth, horizon_days, z_values):
    """Refresh catch-up prior for a history with no movement.

    Newcomers hold the ubiquitous trophies (rate ~100%) at 100% and
    each other trophy at a marginal rate proportional to the square of
    its current rate (early trophies first), summing to
    NEWCOMER_TROPHIES trophies per newcomer on average. The median is
    the diluted mixture; the spread is wide because the next refresh's
    size is a guess.
    """
    usable = [r for r in last_rates if r is not None and r < 99.5]
    denom = sum(r * r for r in usable) or 1.0
    spread = min(1.6, 1.0 + 0.25 * math.sqrt(max(0.0, horizon_days)))
    rows = []
    for i, rate in enumerate(last_rates):
        if rate is None:
            # No observed rate at all: a flat 1% median, wide spread.
            rows.append((i, _quantile_row(_logit(1.0), spread, z_values)))
            continue
        if rate >= 99.5:
            rows.append((i, [99.5, 99.9, 100, 100, 100]))
            continue
        marginal = 100.0 * NEWCOMER_TROPHIES * rate * rate / denom
        median = (rate + (growth - 1.0) * marginal) / growth
        rows.append((i, _quantile_row(_logit(median), spread, z_values)))
    return rows


def forecast_case(case):
    trophies = case.get("trophies") or []
    if not trophies:
        return {"trophies": []}
    levels = case.get("levels") or LEVELS
    z_values = [Z[LEVELS.index(level)] if level in LEVELS else 0.0
                for level in levels]
    start = _release_start(case)
    checkpoint = _parse_instant(case.get("at"))
    target = _parse_instant(case.get("target"))
    horizon_minutes = case.get("horizon_minutes")
    if not isinstance(horizon_minutes, (int, float)) or horizon_minutes < 0:
        horizon_minutes = 0.0
    horizon_days = horizon_minutes / 1440.0
    distinct = _distinct_reads(case, start)

    last_rates = [_last_rate(distinct, i) for i in range(len(trophies))]
    if len(distinct) < 2:
        # No movement in the whole history: expect the next refresh.
        first_hours = distinct[0][0] if distinct else (
            _hours_since(start, checkpoint) if checkpoint is not None else 0.0)
        target_hours = (_hours_since(start, target) if target is not None
                        else first_hours + horizon_minutes / 60.0)
        growth = _refresh_growth(first_hours, target_hours)
        rows = _forecast_flat(last_rates, growth, horizon_days, z_values)
        rows.sort()
        return {"trophies": [{"id": trophies[i]["id"], "q": q} for i, q in rows]}

    last_hours = distinct[-1][0]
    target_hours = (_hours_since(start, target) if target is not None
                    else last_hours + horizon_minutes / 60.0)
    delta_x = max(0.0, _log_time(target_hours) - _log_time(last_hours))

    # Per-trophy trend fits, then tier-median slopes for shrinkage.
    fits = []
    n_points = []
    for i in range(len(trophies)):
        raw, points = _trophy_points(distinct, i)
        n_points.append(len(raw))
        fits.append(_weighted_line(points) if len(points) >= 2 else None)

    tier_slopes = {}
    all_slopes = []
    for i, trophy in enumerate(trophies):
        fit = fits[i]
        if fit is None:
            continue
        tier = str(trophy.get("tier") or "bronze")
        tier_slopes.setdefault(tier, []).append(fit[0])
        all_slopes.append(fit[0])
    global_slope = _median(all_slopes) if all_slopes else 0.0

    rows = []
    for i, trophy in enumerate(trophies):
        rate = last_rates[i]
        if rate is None:
            usable = [r for r in last_rates if r is not None]
            rate = _median(usable) if usable else 1.0
        if rate >= 99.5:
            rows.append((i, [99.5, 99.9, 100, 100, 100]))
            continue
        tier = str(trophy.get("tier") or "bronze")
        tier_list = tier_slopes.get(tier) or []
        prior_slope = _median(tier_list) if len(tier_list) >= 2 else global_slope
        fit = fits[i]
        if fit is not None:
            slope, _intercept, resid_sd, slope_se = fit
            weight = n_points[i] / (n_points[i] + 4.0)
            slope = weight * slope + (1.0 - weight) * prior_slope
            resid = resid_sd if resid_sd is not None else 0.35
            se = slope_se if slope_se is not None else 0.6
        else:
            slope = prior_slope
            resid = 0.35
            se = 0.6
        move = max(-MAX_LOGIT_MOVE, min(MAX_LOGIT_MOVE, slope * delta_x))
        centre = _logit(rate) + move
        spread = math.sqrt(resid ** 2 + (se * delta_x) ** 2
                           + (0.20 * delta_x) ** 2
                           + (0.35 * math.sqrt(horizon_days)) ** 2
                           + 0.10 ** 2)
        spread = min(SPREAD_CAP, max(SPREAD_FLOOR, spread))
        rows.append((i, _quantile_row(centre, spread, z_values)))
    rows.sort()
    return {"trophies": [{"id": trophies[i]["id"], "q": q} for i, q in rows]}


def main():
    DST_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(SRC_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        forecast = forecast_case(case)
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        (DST_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
