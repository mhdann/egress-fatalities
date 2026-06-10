# Replication of "Egress Thresholds and Wildfire Fatalities"

https://www.pnas.org/doi/10.1073/pnas.2535081123

Goal: to understand how the authors approached the analysis linking community egress
(the number of road exits out of a town) to wildfire fatalities, to reproduce their
results from the supplementary data and code, and to test how robust the central claim
actually is.

## What we found

Full write-up: **[egress-fatalities-reanalysis.md](egress-fatalities-reanalysis.md)**
(one-page PDF: [egress-fatalities-reanalysis.pdf](egress-fatalities-reanalysis.pdf)). In short:

- **The headline "threshold at ~6 exits" (Fig S1) is an artifact.** It regresses a
  *reverse cumulative sum* of fatality rate against the variable it was sorted by, which
  is monotonic by construction and almost always produces a breakpoint — even under a
  null relationship.
- **Six population denominators are wrong**, all at low-exit communities and all inflating
  the fatality rate toward the paper's conclusion (post-fire/depopulated census figures, or
  a geographic misassignment). Corrected values are in `data/fire-fatality-corrected.csv`.
  After correction, the per-capita regression (Fig S4) drops below significance
  (p 0.036 → 0.060).
- **A correctly specified count model does show a real effect.** Negative binomial,
  `deaths ~ exits + offset(log population)`: ~16% lower fatality rate per egress road,
  p < 0.0001, stable under leave-one-out jackknife. But there is **no threshold**, and the
  data do not support a causal or policy reading (observational, ~35 communities,
  confounding with community type, selection on fatal events).

**Verdict:** "fewer exits, deadlier" is supported, modestly and on corrected denominators;
the specific *threshold* claim and the Fig S4 per-capita significance are not.

## Contents

| Path | What it is |
|---|---|
| `study/data/pnas.2535081123.sd01.xlsx` | Authors' source fatality workbook (richest, human-audited) |
| `study/data/pnas.2535081123.sd02.csv` | Authors' CSV export consumed by their R scripts |
| `data/fire-fatality-corrected.csv` | Our corrected denominators (idempotent) + corrected rates |
| `study/pnas.2535081123.sd03.r`, `sd04.txt`, `sd05.txt` | Authors' R scripts (regression + spatial pipeline) |
| `study/docs/pnas.2535081123.sapp.pdf` | Authors' SI appendix |
| `docs/figS4_popweighted.png` | Regenerated Fig S4 with a population-weighted regression |
| `egress-fatalities-reanalysis.{md,pdf,tex}` | Our one-page re-analysis (source, PDF, Markdown) |
| `egress-nb-reanalysis.ipynb` | Executable notebook: NB model, robustness suite (run with `.venv`, kernel "Python (egress-fatalities)") |

## Source

Fong, Broderick, Moritz & Halpern (2025), *PNAS*. Authors' data and code:
https://github.com/WRI-Science/roads-pnas
