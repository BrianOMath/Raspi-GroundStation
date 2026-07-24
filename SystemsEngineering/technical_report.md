# Design, Implementation, and Empirical Validation of a VHF Satellite Ground Station for Meteor M2-x LRPT Reception

**B-Raspi Ground Station — Technical Report**
Brian O'Mathúna · SatNOGS Station 4621 · Dublin, Ireland
Draft v0.2 — July 2026

---

## Abstract

A VHF satellite ground station was designed, built, and operated in Dublin, Ireland, to receive and decode Low-Rate Picture Transmission (LRPT) imagery from the Meteor M2-3 and M2-4 weather satellites at 137 MHz. The station comprises a self-built turnstile antenna, a mast-mounted low-noise amplifier, an RTL-SDR receiver, and a Raspberry Pi 4 running an automated capture–decode–analysis pipeline integrated with the SatNOGS network. An RF link budget was constructed from first principles and validated against 21,067 signal-to-noise (SNR) measurements collected across 35 real satellite passes spanning 5°–84° elevation. The measured SNR reproduces the elevation-dependent shape predicted by free-space path loss, confirming the link-budget geometry. The measured rise from horizon to zenith (~13.5 dB) exceeds the flat-gain model prediction (~9.9 dB) by ~3.7 dB; this excess is attributed to the turnstile antenna's elevation gain pattern, which the idealised model deliberately omits — making the model–data discrepancy itself an empirical characterisation of the antenna. Residual scatter (2.2 dB RMS) is attributed to azimuth-dependent antenna lobing and local horizon effects. Decode performance was measured over a 12-day period: the station decoded 41 of 41 passes above 30° elevation, against 35% success in the 20–30° transition band, establishing a practical decode threshold near 30°. The system was verified against a 16-item requirements specification, with 15 requirements closed as passed.

---

## 1. Introduction

Following the decommissioning of the NOAA APT downlinks in August 2025, the Meteor M2-x series became the primary operational target for VHF weather-satellite image reception. This project set out with a dual objective:

1. **Build a working ground station** capable of autonomously receiving, decoding, and publishing Meteor M2-x LRPT imagery; and
2. **Validate the station's own RF link-budget model** against measured data — closing the loop between predicted and observed performance.

The second objective distinguishes this work from a typical reception project: the station carries its own instrumentation (a custom SNR estimator and an orbital-correlation pipeline) so that every pass contributes to a cumulative dataset for model validation.

The station operates as node **4621 ("B-Raspi")** on the [SatNOGS network](https://network.satnogs.org/stations/4621/), providing a publicly verifiable observation record.

## 2. System Description

### 2.1 Architecture

The station follows the architecture captured in the SysML model (`SysML/B-Raspi_v1_2.gaphor`): six hardware subsystems (Antenna, RF Front End, Receiver, Processing, Data, Power) and a software pipeline hosted on the Processing subsystem.

<!-- Figure: hardware BDD export -->
<!-- ![System architecture](docs/braspi_bdd.png) -->

Signal path:

```
Meteor M2-x (LRPT, 137.9 / 137.1 MHz, QPSK 72 kbaud)
   → Turnstile antenna (self-built, tuned ~137.9 MHz)
   → 1 m coax → LNA (SPF5189Z, mast-mounted) → 4 m coax
   → RTL-SDR Blog V3 (bias-T powering the LNA via the coax)
   → Raspberry Pi 4 (SatNOGS client, Docker)
```

### 2.2 RF front-end design decision: LNA placement

The LNA is mast-mounted approximately 1 m from the antenna feedpoint, ahead of the main coax run. Friis cascade analysis (Section 3.1) shows that with the LNA indoors — i.e. ~5 m of coax ahead of it — the cascaded noise figure is 1.62 dB; with the mast-mounted arrangement it improves to 1.23 dB, and total link C/N improves by ~1.0 dB (0.4 dB less pre-amplifier signal attenuation plus 0.6 dB lower noise temperature). DC power is injected onto the coax by the RTL-SDR's integrated bias-T, so no separate power run is required.

### 2.3 Software pipeline

Processing is event-driven: an inotify watcher (`process_meteor.sh`) detects the completion of each IQ recording written by the SatNOGS client and orchestrates, without operator action:

1. **Decode** — SatDump demodulates and decodes the LRPT stream to MSU-MR channel imagery and a false-colour composite.
2. **Signal-quality analysis** — a custom estimator (`iq_snr_trace.py`) computes SNR at 1-second resolution from the raw IQ (Section 3.2); an orbital correlator (`correlate_snr_elevation.py`) tags each sample with satellite elevation and azimuth (Section 3.3).
3. **Publication** — decoded imagery is uploaded to the corresponding SatNOGS observation.
4. **Accumulation** — per-pass records are appended to a persistent cumulative dataset.
5. **Housekeeping** — a scheduled cleanup prunes bulky artefacts after 3 days while preserving all analysis records indefinitely.

A local Flask dashboard provides per-pass review of imagery, SNR-vs-elevation and SNR-vs-time plots, and waterfall displays, independent of the SatNOGS network. Notably, the analysis stage runs for **all** passes, including those too weak to decode — the SNR estimator operates on the raw spectrum and does not require decode success, so failed passes still contribute signal-quality data (relevant to characterising the station's decode threshold).

## 3. Methods

### 3.1 Link-budget model

The link budget (`LinkBudget/meteor_link_budget.m`, parameters in `groundstation_params.m`) computes carrier-to-noise density as a function of elevation:

- **Slant range** from spherical geometry: d(ε) = −R sin ε + √((R+h)² − R² cos² ε), with h = 820 km.
- **Free-space path loss**: FSPL = 20 log₁₀(d) + 20 log₁₀(f) + 20 log₁₀(4π/c).
- **EIRP** = 8.99 dBW (5 W transmit, +3 dBi antenna, −1 dB line loss, published Meteor values).
- **Additional losses** = 2.6 dB (atmospheric 0.5, rain 0.1, polarisation 1.0, pointing/misc 1.0).
- **Cascaded noise figure** (Friis): F = L_pre + (F_LNA − 1)·L_pre + (F_SDR − 1)·L_pre·L_post/G_LNA = 1.23 dB, giving T_sys ≈ 245 K with T_sky = 150 K.
- **Required C/N₀** = 56.07 dBHz (QPSK Eb/N₀ 5.5 dB at BER 10⁻⁵ + 2 dB implementation loss + 10 log₁₀(72 kbps)).

The model predicts link margins of **+11.7 dB at 5° elevation rising monotonically to +22.4 dB at 90°**, i.e. the link closes at all usable elevations. The receive antenna is modelled with a *constant* nominal gain of 1.0 dBi at all angles — a deliberate idealisation whose consequences are examined in Section 5.

### 3.2 SNR estimation from raw IQ

SatDump reports SNR only once, at signal acquisition, which is insufficient for elevation correlation. A custom estimator was therefore built. The raw cs16 IQ recording (160 kHz complex sample rate) is processed in 1-second windows; for each window, the Welch power spectral density is computed and the mean PSD inside the signal's occupied bandwidth is compared with the mean PSD in noise-only guard bands:

- **Occupied bandwidth** = symbol rate × (1 + α) = 72 kHz × 1.5 = **108 kHz** (RRC roll-off α = 0.5), i.e. ±54 kHz about centre.
- **Guard bands**: 59 kHz → 77.6 kHz each side (5 kHz clear of the RRC skirt; inner 97% of Nyquist to avoid anti-aliasing roll-off).
- **DC exclusion**: ±1 kHz, removing the RTL-SDR hardware DC spike from the signal band.

The estimator was validated against synthetic QPSK-plus-noise recordings of known SNR: it tracks true SNR with a consistent ≈ −1.7 dB fixed offset (the signal band necessarily contains signal *plus* noise, and estimator scaling differs from true C/N). Because the offset is constant, the estimator is treated as *shape-accurate but absolutely uncalibrated*; all model comparisons therefore fit a single constant offset and compare only elevation-dependent structure (Section 4.2).

### 3.3 Orbital correlation

Each SNR sample is tagged with the satellite's elevation and azimuth by SGP4 propagation (Skyfield) of the per-observation TLE retrieved from the SatNOGS API, evaluated at the sample's UTC time against the station's WGS84 coordinates. Timestamp zero is the IQ file-creation instant (embedded in the filename), which differs from the nominal observation start by 1–3 s.

The correlator was cross-validated against SatNOGS's independently computed pass geometry: for observation #14326791, maximum elevation agreed to 0.3° (31.7° vs 32.0°) and rise/set azimuths to within 1°.

### 3.4 Dataset

All analysis below uses the cumulative dataset as of 26 June 2026: **21,067 one-second samples across 35 passes**, elevation coverage 5.0°–84.3°, both M2-3 and M2-4, collected with the station's minimum scheduling horizon at 5°.

## 4. Results

### 4.1 Decode performance

Decode success was tallied for all Meteor M2-3 / M2-4 observations scheduled on the station between 12 and 24 July 2026. An observation was scored a success if it yielded at least one decoded MSU-MR image. No observations were excluded; failures attributable to station availability (network loss, manual reset) were counted as failures, since unattended reliability forms part of the requirement under test.

| Max elevation | Decoded | Observations | Success rate |
|---|---|---|---|
| ≥ 30° | 41 | 41 | **100%** |
| 20°–30° | 7 | 20 | 35% |
| ≥ 20° (combined) | 48 | 61 | 78.7% |

**Above 30° elevation the station decoded every pass attempted — 41 consecutive successes with no failures.** Applying the rule of three, this bounds the true success rate above approximately 93% at 95% confidence.

Between 20° and 30°, performance falls sharply to 35%. Every one of the 13 failures in the period occurred within this band. The station therefore exhibits a practical decode threshold near **30°** elevation, rather than the 20° assumed when the performance requirement was originally written.

Against the a-priori requirement of ≥ 80% success above 20° (REQ-P-01), the combined figure of 78.7% is a marginal shortfall. The 95% confidence interval on this measurement spans approximately 68–89% and therefore contains the 80% requirement, so the achieved rate cannot be statistically distinguished from the requirement at this sample size. The requirement is recorded as failed rather than revised, and a replacement requirement derived from the measurement (REQ-P-01b: ≥ 90% success above 30°) is verified as passed. Section 5 discusses the physical basis of the observed threshold.

Decoded imagery has been obtained across the full elevation range, including night-side passes (visible-band channels dark, as expected for the MSU-MR instrument's channel 1–3 configuration).

### 4.2 Measured vs modelled SNR

![All measured points vs model](analysis/outputs/scatter_all_points.png)
*Figure 1 — All 21,067 measured SNR samples (blue) against the link-budget C/N curve (red), the latter shifted by a single fitted constant (−8.25 dB) to account for estimator calibration and bandwidth-definition differences. The dashed curve is the unshifted model.*

![Binned comparison](analysis/outputs/binned_comparison.png)
*Figure 2 — Median measured SNR in 5° elevation bins (with inter-quartile band) against the fitted model. The measured curve is steeper: it crosses the model near 22–25° and sits ~3–4 dB above it at high elevation.*

![Residuals](analysis/outputs/residuals.png)
*Figure 3 — Residuals (measured − model) after the constant-offset fit. The upward trend with elevation indicates a shape difference, not a calibration offset. Residual RMS = 2.24 dB.*

Three findings:

**(i) The path-loss physics is confirmed.** Measured SNR and modelled C/N both rise monotonically with elevation with closely matching curvature at low-to-mid elevations. The slant-range geometry and FSPL formulation are validated.

**(ii) The measured elevation dependence is steeper than the model.** Median measured SNR rises **13.5 dB** from ~7.5° to ~80°, against a model prediction of **9.9 dB**. The ~3.7 dB excess is attributed to the turnstile's real elevation gain pattern — higher gain toward zenith, roll-off toward the horizon — which the constant-gain model omits by construction. The model–data discrepancy therefore constitutes an empirical measurement of the antenna's relative elevation pattern, obtained without an anechoic chamber, using the satellite itself as the far-field source.

**(iii) Residual scatter is azimuth-structured.** After removing the elevation trend, 2.24 dB RMS scatter remains. Single-pass traces show a characteristic double-branch structure: the ascending and descending legs of a pass traverse different azimuths — and hence different antenna lobes — producing systematically different SNR at the same elevation. Preliminary sector analysis at low elevation (5–15°) shows near-uniform mean SNR across N/E/S/W (8.4–9.1 dB), consistent with measurements near the estimator floor rather than strong directional obstruction; a full azimuth–elevation sky map is future work (Section 6).

### 4.3 Requirements verification

The system was verified against a requirements specification covering functional, performance, operational, and interface categories (see `SystemsEngineering/requirements.md` and `SystemsEngineering/verification_matrix.md`). Of 16 requirements, **15 are closed as PASS and one (REQ-P-01) as a marginal FAIL**, with the failure diagnosed in §4.1 as a mis-set elevation threshold rather than a system deficiency. Verification methods span test (measured on the live system), analysis (link budget, Friis cascade), inspection (data formats, configuration), and demonstration (unattended operation, SatNOGS publication).

Notable verification evidence includes: cascaded noise figure 1.23 dB against a ≤ 1.5 dB requirement (analysis, 0.27 dB margin); 100% decode success across 41 consecutive passes above 30° elevation (test); dataset minimum elevation of exactly 5.0° demonstrating the scheduling floor; and the elevation cross-check of §3.3 verifying the orbital correlation by independent comparison. Three accepted limitations and one nonconformance are documented in the matrix.

## 5. Discussion

**What the model captures, and what it deliberately omits.** The link budget treats the receive antenna as an isotropic 1.0 dBi gain at all angles and contains no azimuth dependence. The validation shows precisely the consequences: the elevation *trend* attributable to geometry is reproduced, while the two omissions appear in the data as (i) the steeper measured slope (elevation pattern) and (ii) the azimuth-structured residual (lobing/obstructions). The model is best interpreted as the idealised bounding case — a perfect antenna under perfect conditions — with the measured departures being the real system's signature rather than model failure.

**Measurement honesty.** The absolute offset between measured SNR and modelled C/N (−8.25 dB as fitted) is **not physically meaningful**: the estimator measures a spectral power ratio over the occupied bandwidth, which differs in scale from C/N in the receiver noise bandwidth, and carries its own ≈ −1.7 dB bias. Only the elevation-dependent *shape* constitutes a fair test, and the analysis is constructed accordingly. Attributing the fitted offset to antenna gain would imply a nonsensical effective gain (≈ −7 dBi) and is explicitly rejected.

**Known limitations and nonconformances.** Three accepted limitations are recorded in the verification matrix: (1) automatic recovery after network loss is not a requirement — the Pi occasionally requires manual reset following WiFi outages at the installation location (root cause: marginal WiFi; mitigations identified but deferred); (2) waterfall review requires network access on first fetch (cached thereafter); (3) TLE retrieval fails during network outages, in which case imagery is still produced but that pass contributes no signal-quality record — a small selection bias in the cumulative dataset against outage-coincident passes.

**The decode threshold and the transition band.** The step in decode performance between the 20–30° band (35%) and elevations above 30° (100%) is sharper than the underlying SNR curve alone would suggest, and the two results together locate the station's operating point relative to the decoder's lock threshold. Measured SNR rises steeply through 20–30° and flattens above roughly 35° (§4.2): passes in the transition band therefore sit close to the margin at which the Viterbi decoder can maintain lock, where a difference of a decibel or two decides whether a pass yields imagery. Above 30° the margin is sufficient that no observed pass has failed. Critically, elevation alone does not determine the outcome within the transition band — 35% of those passes did succeed — which implicates the azimuth-dependent effects identified in §4.2(iii): the same nominal elevation can correspond to a strong or weak part of the antenna pattern, or to an obstructed or clear line of sight, depending on the pass geometry. The transition band is thus where the antenna's azimuthal asymmetry becomes operationally decisive rather than merely measurable. This offers a falsifiable prediction for the future sky-map analysis (§6): the 13 observed failures should cluster in azimuth sectors that also show depressed SNR.

**On the two-branch structure.** For a pass with distinct ascending/descending azimuths, the SNR-vs-elevation trace forms a loop rather than a line: the same elevation is visited twice through different antenna lobes. The loop width is therefore a per-pass probe of azimuthal gain asymmetry — near-overhead passes through a azimuthally-symmetric antenna should close the loop. The accumulated data shows persistent loop separation, indicating measurable azimuthal asymmetry in the as-built turnstile.

## 6. Future Work

- **Azimuth–elevation sky map.** Pool all passes into an az/el grid coloured by SNR to (a) test the local-obstruction hypothesis (tall buildings south/east of the station are predicted to appear as azimuth-localised deficits up to ~30° elevation) and (b) map the antenna's azimuthal pattern. This would also yield the station's empirical horizon profile.
- **Decode-quality correlation.** Parse frame-level statistics (CADU sync/Reed-Solomon corrections) to correlate image-line corruption with SNR dropouts rigorously, rather than by visual alignment.
- **Programmatic observation scheduling** via the SatNOGS API, removing the one remaining manual step per pass.
- **Network resilience.** Wired Ethernet or a connectivity watchdog to eliminate the manual-reset nonconformance.
- **Antenna gain refinement.** Replace the nominal 1.0 dBi constant with the empirically-derived elevation pattern of §4.2, closing the loop by feeding measurement back into the model.

## Repository

All code, models, diagrams, and data formats referenced here are available in this repository. The observation record is independently verifiable on the [SatNOGS network (station 4621)](https://network.satnogs.org/stations/4621/).
