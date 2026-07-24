# B-Raspi — Satellite Ground Station

A self-built, automated satellite ground station in Dublin, Ireland, receiving and decoding **Meteor M2-3 / M2-4 LRPT weather imagery at 137 MHz** — designed, modelled, built, and validated end-to-end as a systems engineering case study.

The station runs on the [SatNOGS network](https://network.satnogs.org/stations/4621/) (station **4621, "B-Raspi"**), and every pass feeds an automated pipeline: RF capture → demodulation → image decode → SNR analysis → orbital correlation → upload → local dashboard. The theoretical link budget has been validated against **21,000+ measured data points across 35 real satellite passes**.

Full technical report: design, methods, and measured-vs-modelled validation → (SystemsEngineering/technical_report.md)

---
[System architecture - BDD](docs/groundstation_v1.2_bdd.png)

[System architecture - IBD](docs/groundstation_v1.2_ibd.png)

[RF Frontend](docs/rffrontend_idb.png)

[Software architecture](docs/software_architecture_bdd.png)

---

## Key results

- **Working autonomous ground station** — captures, decodes, and publishes Meteor LRPT imagery with no manual intervention, including self-managed storage cleanup and a live local dashboard.
- **Link budget validated against measurement** — the modelled C/N-vs-elevation curve was compared against 21,067 measured SNR samples (35 passes, 5°–84° elevation). Both rise with elevation as free-space path loss predicts, confirming the slant-range geometry and propagation model.
- **Antenna elevation pattern measured empirically** — the measured SNR rises ~13.5 dB from horizon to zenith versus the model's ~9.9 dB prediction. The ~3.7 dB excess is the turnstile antenna's real elevation gain pattern — a quantity the idealised flat-gain model deliberately omits, extracted here directly from satellite pass data.
- **Custom signal-quality instrumentation** — SatDump only reports SNR once at signal lock, so a custom estimator was built: Welch PSD analysis of the raw IQ recordings, measuring signal-band vs guard-band power second-by-second across each pass, validated against synthetic signals of known SNR.
- **Orbital correlation** — every SNR sample is tagged with satellite elevation and azimuth via SGP4/Skyfield propagation of the per-observation TLE, cross-checked against SatNOGS pass geometry (max-elevation agreement within 0.3°).

## System overview

```
  Meteor M2-x (LRPT, 137.9 / 137.1 MHz, QPSK 72k)
        │
   Turnstile antenna (self-built, tuned ~137.9 MHz)
        │  ~1 m coax
   LNA (SPF5189Z
        │  ~4 m coax
   RTL-SDR Blog V3
        │
   Raspberry Pi 4 ── SatNOGS client (Docker) ── SatNOGS network
        │
   Automated pipeline (inotify-triggered on each new IQ recording):
     ├─ SatDump decode → MSU-MR channel images + false-colour composite
     ├─ SNR estimator (Welch PSD on raw IQ, 1 s resolution)
     ├─ TLE/elevation correlation (Skyfield SGP4)
     ├─ Image upload to SatNOGS observation
     ├─ Per-pass analysis CSV + master dataset append
     └─ Scheduled cleanup (bulky artefacts pruned, analysis data kept)
        │
   Flask dashboard (local network) — imagery, SNR vs elevation,
   SNR vs time, waterfalls, per-satellite display settings
```


## Repository structure

| Folder | Contents |
|---|---|
| **LinkBudget/** | Octave/MATLAB link-budget model. `groundstation_params.m` declares all system primitives (single source of truth); `meteor_link_budget.m` computes the full budget (EIRP, FSPL, Friis noise cascade, G/T, C/N0 margin vs elevation); `snr_vs_elevation.m` produces slant-range, path-loss, and margin curves. Python `compare_measured_vs_model.py` overlays the model on the measured dataset. |
| **Observation Analysis/** | The automated pipeline and instrumentation. IQ-based SNR estimator (`iq_snr_trace.py`), TLE/elevation correlator (`correlate_snr_elevation.py`), per-pass orchestration (`analyse_pass.sh`), decode/upload automation (`process_meteor.sh`), local Flask dashboard (`dashboard.py`), and storage cleanup (`satdump_cleanup.sh`). |
| **OrbitalModelling/** | Orbital mechanics models — Doppler shift prediction and pass geometry. |
| **SysML/** | System architecture model (Gaphor) — block definition and internal block diagrams of the station. |
| **SystemsEngineering** | Requirements specification, verification matrix, and technical report. Requirements-driven development and V&V evidence, structured along ECSS-E-ST-10 / NASA SE Handbook lines. |

## Measured vs modelled

The central engineering question: **does the theoretical link budget predict real performance?**

The comparison method is deliberate about what can and cannot be claimed. The custom SNR estimator measures a spectral power ratio whose absolute scale differs from the model's C/N by a constant (bandwidth definition + estimator calibration), so absolute levels are not directly comparable — but the **elevation-dependent shape is pure physics** (free-space path loss over slant range) and is a fair test. Findings:

1. **The path-loss physics holds.** Measured SNR and modelled C/N both rise monotonically with elevation with closely matching curvature.
2. **The residual shape difference is the antenna.** The measured rise is ~3.7 dB steeper than the flat-gain model — consistent with a real turnstile pattern that gains toward zenith and rolls off toward the horizon. The model-data discrepancy is itself a measurement of the antenna.
3. **Residual scatter (~2.2 dB RMS) is azimuth-dependent** — antenna lobing and local horizon effects that no elevation-only model can capture, visible as a characteristic double-branch in single-pass SNR/elevation traces (ascending vs descending pass legs traverse different antenna lobes).

## Hardware

| Component | Details |
|---|---|
| Antenna | Self-built turnstile, tuned ~137.9 MHz |
| LNA | SPF5189Z wideband (indoors, at receiver) |
| SDR | RTL-SDR Blog V3 |
| Computer | Raspberry Pi 4 |
| Software | SatNOGS client 2.1.2 (Docker), SatDump (built from source), GNU Radio / gr-satnogs, Python 3 (NumPy, SciPy, Skyfield, Flask), Octave, Gaphor |

## Context

Built and operated as a hands-on systems engineering project: requirements-driven design decisions, SysML architecture modelling, first-principles RF analysis (link budget, Friis noise cascade, polarisation), custom instrumentation where off-the-shelf tooling fell short, and closed-loop validation of the model against measured data. NOAA APT transmissions ended in August 2025, making Meteor M2-x LRPT the primary operational target for VHF weather-satellite reception.
