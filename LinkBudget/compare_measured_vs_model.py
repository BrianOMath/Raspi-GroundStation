#!/usr/bin/env python3
"""
compare_measured_vs_model.py

Compares measured SNR-vs-elevation (from all_passes_snr_elevation.csv,
produced by the B-Raspi analysis pipeline) against the idealised link-budget
model (mirroring meteor_link_budget.m / groundstation_params.m).

Key idea on units:
  The measured "SNR" (spectral signal/noise ratio over the OQPSK occupied
  band) and the model's "C/N" (carrier-to-noise in the receiver bandwidth)
  are BOTH signal-to-noise-in-a-bandwidth quantities, so they share the same
  ELEVATION-DEPENDENT shape (driven by free-space path loss). They differ only
  by a CONSTANT dB offset (bandwidth definition + estimator calibration +
  antenna-gain uncertainty). We therefore:
    1. Compare the *shape* (rise with elevation) directly.
    2. Fit a single constant offset (least-squares) to align model to data,
       and report the implied effective antenna gain.

Outputs (PNG):
  1. scatter_all_points.png     — all measured points + model curve (fitted)
  2. binned_comparison.png      — elevation-binned medians + model + fit
  3. residuals.png              — measured minus model, vs elevation
"""

import csv
import math
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# CSV_PATH = "/mnt/user-data/uploads/all_passes_snr_elevation.csv"
CSV_PATH = "C:/Users/brian/OneDrive/Personal Work/GroundStation/LinkBudget/analysis/all_passes_snr_elevation.csv"
# OUT_DIR = "/mnt/user-data/outputs"
OUT_DIR = "C:/Users/brian/OneDrive/Personal Work/GroundStation/LinkBudget/analysis/outputs"

# ---------------------------------------------------------------------------
# Model — mirrors groundstation_params.m + meteor_link_budget.m
# ---------------------------------------------------------------------------
C = 3e8
K_B = 1.38e-23
K_B_DB = 10 * math.log10(K_B)

F_MHZ = 137.9
F_HZ = F_MHZ * 1e6
P_TX_W = 5.0
G_TX_DBI = 3.0
L_TX_DB = 1.0
EIRP_DBW = 10 * math.log10(P_TX_W) + G_TX_DBI - L_TX_DB

ALT_KM = 820
R_KM = 6371

L_ATM, L_RAIN, L_POL, L_MISC = 0.5, 0.1, 1.0, 1.0
L_TOTAL_DB = L_ATM + L_RAIN + L_POL + L_MISC

G_RX_DBI = 1.0          # nominal turnstile gain (the thing we'll effectively fit)
L_COAX_DB = 0.5
G_LNA_DB, NF_LNA_DB, NF_SDR_DB = 20.0, 1.0, 6.5

NF_lna = 10 ** (NF_LNA_DB / 10)
NF_sdr = 10 ** (NF_SDR_DB / 10)
G_lna = 10 ** (G_LNA_DB / 10)
L_coax = 10 ** (L_COAX_DB / 10)
NF_CASCADE = L_coax + (NF_lna - 1) * L_coax + (NF_sdr - 1) * L_coax / G_lna

T_SKY, T_STD = 150, 290
T_SYS = T_SKY + T_STD * (NF_CASCADE - 1)
T_SYS_DBK = 10 * math.log10(T_SYS)

BW_HZ = 150e3


def slant_range_m(el_deg):
    el = np.radians(el_deg)
    return (-R_KM * np.sin(el) +
            np.sqrt((R_KM + ALT_KM) ** 2 - R_KM ** 2 * np.cos(el) ** 2)) * 1e3


def model_CN_dB(el_deg, g_rx_dbi=G_RX_DBI):
    """Model C/N (carrier-to-noise in receiver bandwidth) vs elevation."""
    d_m = slant_range_m(el_deg)
    fspl = 20 * np.log10(d_m) + 20 * np.log10(F_HZ) + 20 * np.log10(4 * np.pi / C)
    pr = EIRP_DBW - fspl - L_TOTAL_DB + g_rx_dbi - L_COAX_DB
    cn0 = pr - K_B_DB - T_SYS_DBK
    return cn0 - 10 * np.log10(BW_HZ)


# ---------------------------------------------------------------------------
# Load measured data
# ---------------------------------------------------------------------------
el, az, snr, obs = [], [], [], []
with open(CSV_PATH) as f:
    for r in csv.DictReader(f):
        el.append(float(r["elevation_deg"]))
        az.append(float(r["azimuth_deg"]))
        snr.append(float(r["snr_db"]))
        obs.append(r["obs_id"])
el = np.array(el); az = np.array(az); snr = np.array(snr)
obs = np.array(obs)
n_pass = len(set(obs))
print(f"Loaded {len(el)} points across {n_pass} passes")
print(f"Elevation {el.min():.1f}-{el.max():.1f} deg, SNR {snr.min():.1f}-{snr.max():.1f} dB")

# ---------------------------------------------------------------------------
# Fit: find the constant dB offset that best aligns model shape to measured data
# (least squares on offset).  measured ≈ model_CN(el) + offset
# ---------------------------------------------------------------------------
model_at_points = model_CN_dB(el)
offset = np.mean(snr - model_at_points)          # LS optimal constant shift
residuals = snr - (model_at_points + offset)
rms = np.sqrt(np.mean(residuals ** 2))

# The offset folds bandwidth + estimator calibration + gain error together.
# If we attribute ALL of it to antenna gain, the implied effective gain is:
implied_gain = G_RX_DBI + offset
print(f"\nFitted constant offset (measured - model): {offset:+.2f} dB")
print(f"RMS of residuals after offset: {rms:.2f} dB")
print(f"If offset attributed entirely to antenna gain -> effective G_rx ~ {implied_gain:+.1f} dBi")

# Shape check: how much does each rise across the elevation span?
lo_mask = (el >= 5) & (el <= 10)
hi_mask = (el >= 70)
meas_rise = np.median(snr[hi_mask]) - np.median(snr[lo_mask])
model_rise = model_CN_dB(80) - model_CN_dB(7.5)
print(f"\nShape check (rise from ~7.5 deg to ~80 deg):")
print(f"  Measured median rise: {meas_rise:.1f} dB")
print(f"  Model predicted rise: {model_rise:.1f} dB")

# ---------------------------------------------------------------------------
# Elevation binning (medians + IQR) for a clean comparison
# ---------------------------------------------------------------------------
bin_edges = np.arange(5, 90, 5)
bin_centers, bin_med, bin_lo, bin_hi, bin_n = [], [], [], [], []
for a, b in zip(bin_edges[:-1], bin_edges[1:]):
    m = (el >= a) & (el < b)
    if m.sum() >= 20:
        bin_centers.append((a + b) / 2)
        bin_med.append(np.median(snr[m]))
        bin_lo.append(np.percentile(snr[m], 25))
        bin_hi.append(np.percentile(snr[m], 75))
        bin_n.append(m.sum())
bin_centers = np.array(bin_centers); bin_med = np.array(bin_med)
bin_lo = np.array(bin_lo); bin_hi = np.array(bin_hi)

# ---------------------------------------------------------------------------
# Plot styling
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "figure.facecolor": "white", "axes.facecolor": "white",
    "font.size": 11, "axes.grid": True, "grid.alpha": 0.3,
    "axes.spines.top": False, "axes.spines.right": False,
})
el_curve = np.linspace(5, 90, 300)

# --- Plot 1: all points + fitted model ---
fig, ax = plt.subplots(figsize=(9, 6))
ax.scatter(el, snr, s=3, alpha=0.15, color="#3b7dd8", label=f"Measured ({len(el)} pts, {n_pass} passes)")
ax.plot(el_curve, model_CN_dB(el_curve) + offset, color="#d1495b", lw=2.5,
        label=f"Link-budget model (shifted {offset:+.1f} dB to fit)")
ax.plot(el_curve, model_CN_dB(el_curve), color="#d1495b", lw=1.2, ls="--", alpha=0.6,
        label="Model, unshifted (nominal 1.0 dBi turnstile)")
ax.set_xlabel("Elevation (degrees)")
ax.set_ylabel("SNR / C-to-N (dB)")
ax.set_title("Measured SNR vs Link-Budget Model — Meteor M2-x, B-Raspi (station 4621)")
ax.legend(loc="lower right", framealpha=0.9)
ax.set_xlim(0, 90)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/scatter_all_points.png", dpi=140)
print(f"\nWrote scatter_all_points.png")

# --- Plot 2: binned medians + IQR band + model ---
fig, ax = plt.subplots(figsize=(9, 6))
ax.fill_between(bin_centers, bin_lo, bin_hi, alpha=0.2, color="#3b7dd8",
                label="Measured inter-quartile range")
ax.plot(bin_centers, bin_med, "o-", color="#1f4e8c", lw=2, ms=6,
        label="Measured median (5° bins)")
ax.plot(el_curve, model_CN_dB(el_curve) + offset, color="#d1495b", lw=2.5,
        label=f"Model (fitted offset {offset:+.1f} dB)")
ax.set_xlabel("Elevation (degrees)")
ax.set_ylabel("SNR / C-to-N (dB)")
ax.set_title("Binned Measured SNR vs Model — shape comparison")
ax.legend(loc="lower right", framealpha=0.9)
ax.set_xlim(0, 90)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/binned_comparison.png", dpi=140)
print("Wrote binned_comparison.png")

# --- Plot 3: residuals ---
fig, ax = plt.subplots(figsize=(9, 5))
ax.scatter(el, residuals, s=3, alpha=0.15, color="#5a8f5a")
# binned residual median
res_med = []
for a, b in zip(bin_edges[:-1], bin_edges[1:]):
    m = (el >= a) & (el < b)
    res_med.append(np.median(residuals[m]) if m.sum() >= 20 else np.nan)
ax.plot((bin_edges[:-1] + bin_edges[1:]) / 2, res_med, "o-", color="#2d5a2d",
        lw=2, ms=6, label="Binned median residual")
ax.axhline(0, color="#d1495b", lw=1.5, ls="--", label="Perfect model fit")
ax.set_xlabel("Elevation (degrees)")
ax.set_ylabel("Measured − Model (dB)")
ax.set_title(f"Residuals after constant-offset fit (RMS = {rms:.2f} dB)")
ax.legend(loc="upper right", framealpha=0.9)
ax.set_xlim(0, 90)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/residuals.png", dpi=140)
print("Wrote residuals.png")

print("\n=== SUMMARY ===")
print(f"Model shape rise (7.5->80 deg): {model_rise:.1f} dB")
print(f"Measured shape rise            : {meas_rise:.1f} dB")
print(f"Constant offset (calibration)  : {offset:+.2f} dB")
print(f"Residual RMS after offset      : {rms:.2f} dB")
