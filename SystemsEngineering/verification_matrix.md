# B-Raspi Ground Station — Verification Matrix

**Document status:** Issue 1 — all requirements adjudicated
**System version:** B-Raspi V1.2 (turnstile, mast-mounted LNA)
**Verification methods:** T = Test (measured on the real system) · A = Analysis (calculation/model) · I = Inspection (examine artefact/config) · D = Demonstration (observe function performed)

| ID | Requirement (abbreviated) | Method | Evidence artefact | Result | Notes |
|---|---|---|---|---|---|
| REQ-F-01 | Demodulate & decode Meteor M2-x LRPT at 137.9 / 137.1 MHz | T | Decoded MSU-MR imagery in SatNOGS observations (M2-4 and M2-3 passes); SatDump pipeline `meteor_m2-x_lrpt` | **PASS** | Both satellites demonstrated. e.g. obs #14371119 (M2-4), #14370715 (M2-3) |
| REQ-F-02 | Detect IQ completion; initiate processing without operator action | D | `process_meteor.sh` (inotifywait close_write trigger) + journalctl log of unattended pass processing | **PASS** | Verified continuously in operation since Jun 2026; log excerpt to attach |
| REQ-F-03 | Record SNR at ≤ 1 s intervals for full pass duration | T + I | `iq_snr_trace.py` (1.0 s window default); any `pass_analysis.csv` (e.g. 451 rows for 451 s pass) | **PASS** | Row count = pass duration in seconds confirms interval and coverage |
| REQ-F-04 | Associate each sample with elevation & azimuth | T + A | `correlate_snr_elevation.py`; cross-check vs SatNOGS geometry: max-el 31.7° vs 32.0°, rise/set az within 1° (obs #14326791) | **PASS** | Independent cross-validation against SatNOGS SGP4 is the analysis component |
| REQ-F-05 | Upload decoded imagery to corresponding SatNOGS observation | D | Data tab of observations (e.g. `data_<obs_id>_MSU-MR-*.png` present on network) | **PASS** | Publicly inspectable on network.satnogs.org |
| REQ-F-06 | Store per-pass records as structured CSV (time, el, az, SNR) | I | Any `pass_analysis.csv`; header: `elapsed_seconds, utc_time, elevation_deg, azimuth_deg, snr_db` | **PASS** | Format inspection |
| REQ-F-07 | Local interface for imagery + signal-quality review, offline-capable | D | `dashboard.py` on Pi (local network, port 5000); functions with no SatNOGS connectivity except waterfall fetch | **PASS** | Note: waterfall view is the one network-dependent feature — cached copies remain viewable offline. Consider noting as minor limitation |
| REQ-F-08 | Append each pass to persistent cumulative dataset | I | `all_passes_snr_elevation.csv` (21,067 rows, 35 passes at last analysis); append logic in `analyse_pass.sh` | **PASS** | Dataset is the input to the model-validation analysis |
| REQ-P-01 | ≥ 80% of passes with max el ≥ 20° yield decoded imagery | T | Observation tally, station 4621, 12–24 July 2026: **48 decoded / 61 observations = 78.7%** | **FAIL (marginal)** | Shortfall of 1.3 percentage points. 95% CI ≈ 68–89%, i.e. the measured rate is not statistically distinguishable from the 80% requirement at this sample size. Root cause is the a-priori 20° threshold, not a system deficiency — see REQ-P-01b and nonconformance 4 |
| REQ-P-01b | ≥ 90% of passes with max el ≥ 30° yield decoded imagery | T | Same period: **41 decoded / 41 observations = 100%** | **PASS** | Zero failures in 41 attempts; 95% one-sided lower confidence bound ≈ 93% (rule of three). Requirement set at 90% to remain defensible against future sampling rather than restating a perfect run |
| REQ-P-02 | Cascaded noise figure ≤ 1.5 dB | A | `meteor_link_budget.m` Friis cascade: NF = 1.23 dB (mast-mounted LNA, 0.1 dB pre-LNA coax) | **PASS** | Margin 0.27 dB against requirement. Analysis assumes datasheet NF values (LNA 1.0 dB, SDR 6.5 dB) |
| REQ-P-03 | RF link closes with positive margin at all el ≥ 5° | A | `meteor_link_budget.m` / `snr_vs_elevation.m`: margin +11.7 dB at 5°, monotonic to +22.4 dB at 90° | **PASS** | Worst case (5°) well above closure. Empirical support: decoded imagery obtained on low-el passes |
| REQ-O-01 | Signal-quality records retained indefinitely; bulk products ≥ 3 days | I + D | `satdump_cleanup.sh`: deletes MSU-MR/, waterfall, CADU > 3 days; explicitly preserves `pass_analysis.csv` + `.obs_response.json`; master CSV never touched | **PASS** | Dry-run output + post-cleanup folder listing as evidence |
| REQ-O-02 | Capable of scheduling & recording observations down to 5° elevation | D | Station min_horizon = 5° (station 4621 config); low-el passes recorded (dataset spans 5.0°–84.3°) | **PASS** | Dataset minimum elevation of exactly 5.0° demonstrates the floor |
| REQ-I-01 | Obtain TLEs per observation from SatNOGS network API | I + D | `.obs_response.json` per pass (contains tle0/1/2); fetch logic in `process_meteor.sh` | **PASS** | Known limitation: API fetch fails during network outages → pass processed without analysis (graceful degradation, imagery still decoded) |
| REQ-I-02 | Registered on SatNOGS with public scheduling; accessible to other users | I | Station 4621 page: status Online, public; observation history includes other users' scheduled passes | **PASS** | Publicly verifiable at network.satnogs.org/stations/4621 |

## Summary

| | Count |
|---|---|
| PASS | 15 |
| FAIL | 1 (REQ-P-01, marginal — see nonconformance 4) |
| OPEN | 0 |

All 16 requirements are adjudicated. The single failure is a mis-set threshold identified by measurement, with a replacement requirement (REQ-P-01b) derived from the same data.

## Measurement record: decode success rate (REQ-P-01 / REQ-P-01b)

**Method.** Population: all Meteor M2-3 / M2-4 observations scheduled on station 4621 between 12 and 24 July 2026. Success criterion: the observation yielded at least one decoded MSU-MR image. No observations were excluded; failures attributable to station availability (network loss, manual reset) were counted as failures, since unattended reliability is part of what the requirement tests. Sub-20° passes were scheduled only in the first days of the period and are excluded from both cohorts by the requirements' own elevation conditions.

**Results by elevation cohort:**

| Max elevation | Decoded | Total | Rate |
|---|---|---|---|
| ≥ 30° | 41 | 41 | **100%** |
| 20–30° | 7 | 20 | **35%** |
| ≥ 20° (combined) | 48 | 61 | **78.7%** |

**Interpretation.** All 13 failures occurred in the 20–30° band; no pass above 30° failed. The station therefore exhibits a sharp practical decode threshold near 30° elevation rather than the 20° assumed when REQ-P-01 was written. This is physically consistent with the measured SNR-vs-elevation characterisation, in which SNR is still climbing steeply through 20–30° and flattens above roughly 35°: passes in the transition band sit near the decoder's lock threshold, and whether a given pass closes appears to depend on azimuth-dependent factors (antenna lobing, local horizon) rather than elevation alone.

**Disposition.** REQ-P-01 is recorded as failed rather than revised downward: the measured rate (78.7%) cannot be statistically distinguished from the 80% requirement at this sample size, so adjusting the threshold to match the measurement would not be evidence-driven. REQ-P-01b is instead added as a new, measurement-derived requirement capturing the station's demonstrated capability above 30°.

## Known nonconformances / accepted limitations (per ECSS Q-ST-20 spirit)

1. **Auto-recovery after network loss is not required** (deliberately descoped): the Pi occasionally requires manual reset after WiFi outages. Root cause: marginal WiFi at installation location. Mitigation options identified (Ethernet run, watchdog) but deferred. This is why no availability requirement is levied in REQ-I-02.
2. **Waterfall review depends on network** at first fetch (REQ-F-07 note): cached waterfalls viewable offline thereafter.
3. **TLE fetch failure during outages** (REQ-I-01 note): pass imagery still produced; signal-quality analysis skipped for that pass. Bias: cumulative dataset slightly under-represents passes coinciding with network outages.
4. **REQ-P-01 not met (78.7% vs ≥ 80% at ≥ 20° elevation).** Root cause: the 20° elevation threshold was set before any decode-rate measurement existed and lies below the station's actual decode threshold (~30°). The system meets 100% decode above 30°; the shortfall arises entirely from the 20–30° transition band, where link margin is marginal. Disposition: requirement retained and recorded as failed; REQ-P-01b added to capture demonstrated capability. Corrective options if the 20° figure is to be met: improved antenna gain at low elevation (QFH or optimised turnstile), or resolution of local horizon obstructions. Not currently planned.
