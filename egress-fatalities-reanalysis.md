# Re-analysis of *"Egress Thresholds and Wildfire Fatalities"* (Fong et al., PNAS 2025)

**A replication review of [doi:10.1073/pnas.2535081123](https://www.pnas.org/doi/10.1073/pnas.2535081123).**
Data: 38 fire × census-place records (SI dataset `sd01.xlsx`). Numerator = place-attributed
("Identified") fatalities; denominator = place population.

## Issues found

1. **The headline figure regresses a cumulative sum against its own sort key.** Figure S1's
   y-axis, `cum_per_fatal`, is a *reverse cumulative sum* of per-capita fatality rate, ordered by
   exits. This is invalid:
   - It is **monotonically decreasing by construction** (sum of non-negative increments), pinned at
     the grand total at fewest-exits and **exactly 0** at most-exits — so a negative slope is
     guaranteed regardless of the data, and appears even under a null/permuted relationship.
   - A piecewise "breakpoint" is **nearly inevitable** for any such curve; the reported threshold
     (~6.3 exits / 66.6th pct) merely marks where the right-skewed exit distribution concentrates.
   - Points are **not independent** (each is a running total of the others), so the reported
     standard errors, R², and breakpoint CI are not interpretable.

2. **Weighting is unstable.** Re-running the per-capita regression across weighting schemes slides
   the slope by ~2.5× (unweighted R²≈0.09 → population-weighted R²≈0.19 but slope *halves*). A result
   that swings on a weighting aesthetic is not robust; OLS-on-a-ratio is the wrong model for noisy
   count data.

3. **Six population denominators are wrong — and the error is systematic.** For destructive older
   fires the listed population reflects the *post-fire depopulated* census, not the at-risk
   population. **All six biased communities sit at the low-exit end (≤6 exits) and all are inflated**,
   pushing directly toward the paper's conclusion. Two are the dataset's #1 and #2 highest rates.

   | Fire / place | exits | deaths | listed pop → corrected | rate inflation |
   |---|---|---|---|---|
   | Camp / Paradise | 6 | 66 | 7,730 → 26,800 | 3.5× |
   | Camp / Concow | 6 | 9 | 306 → 710 | 2.3× |
   | Carr / Keswick | 3 | 4 | 141 → 451 | 3.2× |
   | Butte / Mountain Ranch | 2 | 2 | 256 → 1,628 | 6.4× |
   | Mtn View / Walker | 2 | 1 | 401 → 704 | 1.8× |
   | Waldo Canyon / Manitou | 3 | 2 | 235 → 4,309 | ≥20× (misassigned*) |

   *Manitou: the deaths occurred in the Mountain Shadows neighborhood of Colorado Springs, not in
   Manitou Springs — a geographic misassignment, not just a stale vintage.

## Impact on the authors' interpretations

- **"Threshold at ~6 exits" — not supported.** It is an artifact of the cumulative transform; a
  correctly specified count model shows a *smooth, constant-per-exit* decline with no kink.
- **Figure S4 per-capita significance — does not survive correction.** Re-running
  `fatality_pct ~ exits` on corrected denominators moves it from **p = 0.036 to p = 0.060**
  (slope −28%), i.e. below conventional significance. The paper reported p = 0.048.
- **Causal / policy reading — unsupported.** Observational data, ~35 communities, confounding
  (exits proxies small/remote/rural community type; their own Fig S3: pop~exits R²=0.43), selection
  on fatal events (no control group of well-connected communities that burned with zero deaths), and
  irreducibly fuzzy tiny-CDP denominators.

## What *does* hold up (negative-binomial + jackknife)

Modeling counts directly — `deaths ~ exits + offset(log population)`, negative binomial (the right
spec; Poisson is badly overdispersed, Pearson φ≈16, α≈1.1):

| | rate ratio / exit | effect | p |
|---|---|---|---|
| Original populations | 0.813 | −18.7% / exit | < 0.0001 |
| **Corrected populations** | **0.837** | **−16.3% / exit** | **< 0.0001** |

- **Direction is real and survives everything** — the cumulative-artifact fix, the denominator
  corrections, and overdispersion (quasi-Poisson p = 0.0014).
- **Jackknife (leave-one-out) is rock-stable**: coefficient range −0.196 to −0.168 across all 38
  deletions; the single most influential point is *Altadena*, whose removal *strengthens* the effect.
  No community drives the result.
- (The corrected OLS per-capita slope is stable to LOO but now leans on un-benchmarkable tiny CDPs —
  Moskowite Corner 109, Igo 148, Ono 72 — another reason to prefer the count model.)

## Verdict

> **"Fewer egress roads → higher per-capita wildfire fatality" is supported — modestly (~16% per
> road), robustly, and on corrected denominators. The paper's specific claims — a 6-exit *threshold*
> and the Figure S4 per-capita significance — are not. No causal or policy conclusion is warranted.**

*Artifacts: idempotent corrections + corrected dataset in `data/fire-fatality-corrected.csv`.
Census figures verified against U.S. Census 2010/2020 profiles and contemporaneous reporting.*
