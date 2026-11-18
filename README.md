# Launch-Day Twitch Viewer Forecaster

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Nawadays-ai/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/Nawadays-ai/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

Entry for the make.fun bounty **gta6-twitch-ccu-forecast-01**: forecast a big
game launch day's Twitch viewers hour by hour. The program reads one case
file per run — everything recorded up to the end of the release day's first
hour (00:00–01:00 UTC), including that hour's viewer count and the hourly
curves of dozens of past big launches — and writes, for each hour 2..24,
five quantiles (5/25/50/75/95%) of that hour's viewer count. Scoring is the
mean pinball loss on the log scale.

## Approach

The forecast is anchored on the observed first hour and shaped by the past
launches bundled in the case itself:

1. **Log-ratio shape.** For every comparable launch, its release-day curve
   becomes 23 numbers: `ln(viewers_h / viewers_1)` for h = 2..24. In that
   space a launch day has a stable anatomy — near the anchor in the small
   hours, a midday dip, a climb to an evening peak around hours 19–23 UTC.
2. **Pool selection.** Only comparables whose own day was *already at scale*
   in hour 1 teach the shape: their hour-1 count must be at least 15% of
   their day's peak. This keeps out launches whose main unlock landed later
   in the UTC day (a single global unlock at 14:00Z, say), whose hour-1
   anchor means something entirely different — their peaks run to hundreds
   of times their first hour, a regime this contest's rolling
   midnight-local console launches are not in. A guard checks the case's
   own first hour against its pre-release history; if it is not at launch
   scale, the full pool is used instead.
3. **Size weighting.** Each pool member is weighted by a Gaussian kernel on
   log hour-1 size (bandwidth 0.8), so launches of similar scale speak
   loudest. The bandwidth widens automatically whenever the weighted pool
   would otherwise collapse below eight effective members — a launch bigger
   than every comparable must not rest on two or three neighbours.
4. **Per-hour normal fit.** For each hour, the weighted mean of the
   log-ratios is the centre and the weighted standard deviation (floored at
   0.12, capped at 1.20) is the spread. Quantiles are
   `q_tau(h) = p1 * exp(mu_h + z_tau * sigma_h)`, rounded to 2 decimals,
   clamped to (0, 1e9], and kept non-decreasing.

If a case carried no usable comparables at all, the program falls back to
flat persistence with a slowly widening band, so the output is always valid.

## Validation

Leave-one-out over the kit's comparables (each at-scale launch forecast from
all the others, scored exactly as the contest scores): **0.203** mean
pinball loss versus **0.265** for the flat persistence baseline — about 23%
lower. Synthetic stress tests (levels rescaled ×0.05 and ×20, multiplicative
log noise, peaks shifted ±3 hours) keep the model at or near the baseline in
the worst, deliberately out-of-regime cells and clearly ahead in-regime.
Runtime is ~0.05 s per case; output is byte-for-byte deterministic.

## Honest limitations

- The shape is an average over past launches; any single launch's real curve
  (a server outage, a surprise streamer event) can sit far from it.
- The pool is small (a few dozen launches), so the per-hour spread is an
  estimate with real sampling error, and launches far outside the pool's
  size range are extrapolations even with the adaptive bandwidth.
- Only the first hour anchors the level; the model does not use the
  within-hour trend or channel counts.

Pure Python 3 standard library, no network, deterministic.
