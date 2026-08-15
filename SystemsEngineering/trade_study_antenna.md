# Trade Study — Antenna Selection and Station Performance Improvement

**B-Raspi Ground Station · SatNOGS Station 4621**
**Document status:** Issue 1
**Related:** `requirements.md`, `verification_matrix.md`, `technical_report.md`

---

## 1. Purpose

Originally the plan was to upgrade from a V-dipole antenna to a quadrifilar helix (QFH) antenna, however I decided to change the plan and upgrade to a turnstile antenna instead of the QFH. This document records the comparison and justifies the decision to build a turnstile, furthermore this document will examine the measurements taken since the station became operational.

## 2. Problem statement

### 2.1 Assumptions

The initial reasoning was that received signal strength limited decode success, and that antenna gain and polarisation match are factors that will improve it.

### 2.2 What the measurements show

**The link budget is not the binding constraint.** Modelled link margin is +11.7 dB at 5° elevation, rising to +22.4 dB at 90° (`meteor_link_budget.m`). The link closes with substantial margin across the entire usable elevation range. Adding antenna gain increases a margin that is already sufficient.

**A near-field obstruction is the binding constraint.** Sky-map analysis of the residual between measured SNR and the link-budget model (`sky_map_analysis.py`) shows a direction-dependent deficit of 5–6 dB across the western half of the sky, persisting to 35–50° elevation:

| Sector    | 15–25° | 25–40° | Physical feature        |
|---------------|------------|------------|-----------------------------|
| E (068–113°)  | −1.5 dB    | −0.4 dB    | open                        |
| S (158–203°)  | −3.5 dB    | −0.3 dB    | open above ~25°             |
| SW (203–248°) | −5.1 dB    | −2.5 dB    | chimney (~2 m from antenna) |
| W (248–293°)  | −5.8 dB    | −5.5 dB    | roof ridge                  |
| NW (293–337°) | −6.0 dB    | −5.7 dB    | roof ridge                  |
| N (337–023°)  | −5.3 dB    | −4.2 dB    | roof slopes up (<10 m)     |

**Decode outcomes confirm the near-field obstruction independently.** For passes with maximum elevation 20–40° (matched geometry), classified by culmination azimuth:

| Culmination          | Decoded | Rate |
|--------------------------|-------------|----------|
| Eastern half (NE–E–SE–S) | 27/28       | **96%**  |
| Western half (SW–W–NW–N) | 10/27       | **37%**  |

A 2.6× difference in decode rate between halves of the sky, at matched elevation, attributable to site geometry rather than to the receive chain.

### 2.3 Restated problem

The measurements change the problem from "which antenna is best" to "what factors limit station performance"

## 3. Options considered

| ID | Option                | Description                                                                            |
|--------|---------------------------|--------------------------------------------------------------------------------------------|
| **A**  | Turnstile (current)       | Self-built crossed dipoles fed in quadrature; circular polarisation; hemispherical pattern |
| **B**  | QFH                       | Quadrifilar helix; circular polarisation; better low-elevation gain and axial ratio        |
| **C**  | V-dipole                  | Two elements in a V; linear polarisation; simplest build                                   |
| **D**  | Patch / directional       | High gain, narrow beam; requires tracking rotator for LEO                                  |
| **E**  | Raise mast above roofline | No antenna change; relocate current antenna to clear the obstruction                       |
| **F**  | No change                 | Retain current configuration                                                               |

## 4. Evaluation criteria

| Criterion                                            | Weight | Rationale                                                                               |
|----------------------------------------------------------|------------|---------------------------------------------------------------------------------------------|
| Expected improvement against the **measured** limitation | 35%        | The limitation is obstruction; options are judged on what they recover, not on nominal gain |
| Low-elevation pattern performance                        | 15%        | Where marginal passes are won or lost                                                       |
| Polarisation match to RHCP downlink                      | 10%        | Fixed 3 dB penalty for linear; ~1 dB residual for practical CP                              |
| Build complexity / risk of construction error            | 15%        | Self-built; a poorly built antenna underperforms its theory                                 |
| Cost                                                     | 10%        | Hobby budget                                                                                |
| Weatherproofing / mechanical durability                  | 10%        | Exposed roof mounting, Irish coastal climate                                                |
| Suitability without a rotator                            | 5%         | Station has no tracking hardware                                                            |

The dominant criterion is measured improvement, because the electrical performance is already adequate.

## 5. Comparison

### 5.1 Technical characteristics

|                        | A: Turnstile | B: QFH                     | C: V-dipole | D: Patch         | E: Raise mast |
|------------------------|------------------|--------------------------------|-----------------|----------------------|-------------------|
| **Polarisation**       | RHCP             | RHCP                           | Linear          | RHCP                 | unchanged         |
| **Nominal peak gain**  | ~1 dBi           | ~2–4 dBi                       | ~2.15 dBi       | 6–9 dBi              | unchanged         |
| **Low-elevation gain** | moderate         | good                           | poor–moderate   | poor (off-boresight) | unchanged         |
| **Pattern**            | hemispherical    | hemispherical, fuller          | figure-of-eight | narrow beam          | unchanged         |
| **Polarisation loss**  | ~1 dB            | ~1 dB                          | 3 dB            | ~1 dB                | unchanged         |
| **Needs rotator**      | no               | no                             | no              | yes                  | no                |
| **Build difficulty**   | moderate         | high (helix geometry, phasing) | low             | moderate             | n/a               |
| **Cost (build/buy)**   | ~€20 / €90       | ~€35 / €150                    | ~€10            | ~€60+                | ~€30 materials    |

### 5.2 Expected improvement against the measured limitation

**Antenna options (A–D)** raise received signal uniformly, or alter the pattern shape. Neither removes a diffraction loss caused by a solid object in the propagation path. A gain increase of 1–3 dB would partially offset a 5–6 dB obstruction deficit — lifting some marginal western passes above the decode threshold — but cannot recover the obstructed sky. Estimated benefit in the western sector: **1–3 dB**, insufficient to close a 5–6 dB deficit.

**Option E** removes the obstruction geometrically. Sensitivity analysis of clearance angle at the worst bearing (278°, currently clearing at 50°):

| Ridge distance | Ridge height above antenna | Clearance after +0.5 m | +1.0 m | +1.5 m |
|--------------------|--------------------------------|----------------------------|------------|------------|
| 1.5 m              | 1.8 m                          | 41°                        | 28°        | 11°        |
| 2.0 m              | 2.4 m                          | 43°                        | 35°        | 24°        |
| 3.0 m              | 3.6 m                          | 46°                        | 41°        | 35°        |

A 1–1.5 m raise recovers most of the obstructed sector for a close ridge, less for a distant one. Clearing 50° → 25° over the affected ~90° azimuth sector recovers approximately **8.6% of the full hemisphere**. Applying the measured eastern decode rate to western passes implies roughly **16 additional successful passes per 27 western observations**.

### 5.3 Weighted assessment

Scores 1–5, where 5 is best.

| Criterion                      | Wt | A: Turnstile | B: QFH | C: V-dipole | D: Patch | E: Raise mast | F: No change |
|------------------------------------|--------|------------------|------------|-----------------|--------------|-------------------|------------------|
| Improvement vs measured limitation | 35%    | 2                | 3          | 1               | 2            | 5                 | 1                |
| Low-elevation pattern              | 15%    | 3                | 4          | 2               | 1            | 3                 | 3                |
| Polarisation match                 | 10%    | 4                | 4          | 1               | 4            | 4                 | 4                |
| Build complexity / risk            | 15%    | 4                | 2          | 5               | 3            | 3                 | 5                |
| Cost                               | 10%    | 4                | 3          | 5               | 2            | 4                 | 5                |
| Weatherproofing / durability       | 10%    | 4                | 3          | 4               | 3            | 2                 | 4                |
| No rotator required                | 5%     | 5                | 5          | 5               | 1            | 5                 | 5                |
| Weighted total                     |        | 3.25             | 3.20       | 2.55            | 2.20         | 3.95              | 3.15             |

## 6. Findings

**Finding 1 — Option E (raise mast) is the technically superior choice.** It addresses the measured limitation directly and offers roughly 5–6 dB of recovery across half the sky, against 1–3 dB for the best antenna alternative. No antenna change scores close to it.

**Finding 2 — The turnstile was, and remains, the correct antenna choice.** Options A and B score within 0.05 of each other. The QFH's advantage in low-elevation gain is real but modest, and is offset by materially higher build difficulty: helix geometry and phasing-line length are unforgiving, and a poorly built QFH underperforms a well-built turnstile. Given the antenna is self-built and unmeasured, the lower-risk build is the sounder engineering choice. The V-dipole is clearly inferior on polarisation alone (3 dB fixed penalty). The patch is unsuitable without a rotator.

**Finding 3 — Antenna choice is second-order.** The spread across all four antenna options (2.20–3.25) is smaller than the gap between the best antenna and Option E (3.25 → 3.95). Effort spent selecting between antennas addresses the wrong variable.

**Finding 4 — The station already meets its requirements.** REQ-P-01b (≥90% decode above 30° elevation) verifies at 98.8% (79/80 passes). REQ-P-01 (≥80% above 20°) verifies at 84.2% (96/114). No option is required to achieve specification; all are improvements beyond it.

## 7. Recommendation

**Retain the current configuration (Option F), with Option E identified as the preferred improvement should site constraints change.**

Rationale:

1.  Option E is excluded by **site constraints, not technical merit**. Raising the mast above the roofline is not practical at this installation. This is a constraint-driven exclusion and is recorded as such rather than being reflected in the technical scoring.

2.  With E unavailable, no remaining option offers benefit proportionate to its cost and risk. The best available alternative (QFH, Option B) scores 3.20 against the incumbent turnstile's 3.25 — i.e. **no net improvement** — while requiring a difficult build, roof access, and a period of station downtime.

3.  The station meets its performance requirements as configured (Finding 4).

4.  The obstruction is now **characterised and documented**, which converts an unknown limitation into a known one. Operationally, this is actionable without any hardware change: passes culminating in the eastern half decode at 96% versus 37% in the western half at matched elevation, so scheduling can favour eastern passes when observation time is limited.

## 8. Conditions that would reopen this decision

- **Site change** making a mast raise or relocation practical — Option E becomes the recommendation immediately.

- **A measured antenna pattern** for the current turnstile showing it underperforms its nominal characteristics materially. Present gain figures are estimates; the elevation pattern has been characterised empirically (~3.7 dB zenith-to-horizon variation) but the azimuthal pattern has not been separated from the obstruction.

- **A change of target satellite** to a band or modulation where link margin, rather than obstruction, becomes limiting.

- **Acquisition of a rotator**, which would make directional options (D) viable and change the comparison substantially.

## 9. Limitations of this study

- Antenna gain figures for options B–D are published typical values, and not measurements that have been gathered here. The current turnstile's gain is a nominal estimate (1.0 dBi); no anechoic measurement exists.

- The obstruction deficit (5–6 dB) and the mast-raise benefit are derived from the same measurement set. The geometry in §5.2 is parameterised because the ridge distance and height have not been surveyed; the clearance figures are therefore a sensitivity analysis, not a prediction.

- Scoring weights encode judgement about what matters at this station. A different station without an obstruction, or with a link-margin-limited budget would weight differently and could reasonably reach a different conclusion.

- The eastern/western decode-rate comparison controls for maximum elevation but not for other pass characteristics (duration, satellite, time of day).
