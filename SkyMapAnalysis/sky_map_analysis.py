#!/usr/bin/env python3
"""
sky_map_analysis.py

Builds an azimuth-elevation sky map of the residual between measured SNR and
the link-budget model, to identify direction-dependent losses the model does
not account for (antenna pattern asymmetry, local horizon obstructions).

Why residuals rather than raw SNR
---------------------------------
Raw SNR is dominated by the elevation trend from free-space path loss, which
would swamp any azimuthal structure. Subtracting the model removes the part of
the variation that is understood, leaving only what is not.

Estimator non-linearity correction
----------------------------------
The SNR estimator compares mean PSD in the signal band against the noise band.
The signal band contains signal *plus* noise, so it reports 10log10(1 + S/N),
not S/N. This reads high by ~3 dB at low SNR and converges to correct above
about 15 dB. Since obstructions act at low elevation where the bias is largest,
the raw residual would understate them. This script inverts the relationship to
recover true S/N before computing residuals.

    reported = 10log10(1 + S/N)  ->  S/N = 10^(reported/10) - 1

Outputs:
    skymap_residual.png       az/el map of mean residual
    skymap_coverage.png       samples per bin (reliability of each cell)
    horizon_profile.png       recovery elevation vs azimuth, with failed passes
    snr_elevation_by_azimuth.png   two-branch structure coloured by azimuth
    skymap_report.txt         numerical findings by sector
"""

import csv
import math
import os
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import TwoSlopeNorm

CSV_PATH = "/mnt/user-data/uploads/all_passes_snr_elevation.csv"
OUT_DIR = "/mnt/user-data/outputs"



SNR_FLOOR_DB = 5.0      # exclude recording-dropout samples (see report)

# ---------------------------------------------------------------------------
# Link-budget model — mirrors groundstation_params.m / meteor_link_budget.m
# ---------------------------------------------------------------------------
C = 3e8
K_B_DB = 10 * math.log10(1.38e-23)
F_HZ = 137.9e6
EIRP_DBW = 10 * math.log10(5.0) + 3.0 - 1.0
ALT_KM, R_KM = 820, 6371
L_TOTAL_DB = 0.5 + 0.1 + 1.0 + 1.0
G_RX_DBI = 1.0
L_PRE_DB, L_POST_DB = 0.1, 0.4
G_LNA_DB, NF_LNA_DB, NF_SDR_DB = 20.0, 1.0, 6.5
BW_HZ = 150e3

_l_pre = 10 ** (L_PRE_DB / 10)
_l_post = 10 ** (L_POST_DB / 10)
NF_CASCADE = (_l_pre + (10 ** (NF_LNA_DB / 10) - 1) * _l_pre
              + (10 ** (NF_SDR_DB / 10) - 1) * _l_pre * _l_post / 10 ** (G_LNA_DB / 10))
T_SYS = 150 + 290 * (NF_CASCADE - 1)
T_SYS_DBK = 10 * math.log10(T_SYS)


def model_cn_db(el_deg):
    """Modelled carrier-to-noise in the receiver bandwidth, vs elevation."""
    el = np.radians(el_deg)
    d_m = (-R_KM * np.sin(el)
           + np.sqrt((R_KM + ALT_KM) ** 2 - R_KM ** 2 * np.cos(el) ** 2)) * 1e3
    fspl = 20 * np.log10(d_m) + 20 * np.log10(F_HZ) + 20 * np.log10(4 * np.pi / C)
    pr = EIRP_DBW - fspl - L_TOTAL_DB + G_RX_DBI - L_PRE_DB
    return pr - K_B_DB - T_SYS_DBK - 10 * np.log10(BW_HZ)


def correct_estimator_bias(reported_db):
    """Recover true S/N from the estimator's (S+N)/N reading.

    Values at or below 0 dB reported cannot be inverted (they imply no signal);
    they are returned as NaN and excluded downstream.
    """
    lin = 10 ** (np.asarray(reported_db, dtype=float) / 10) - 1.0
    out = np.full_like(lin, np.nan)
    valid = lin > 0
    out[valid] = 10 * np.log10(lin[valid])
    return out


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def load():
    el, az, snr, oid, decoded = [], [], [], [], []
    excluded = 0
    with open(CSV_PATH, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("in_scope") != "1":
                continue
            s = float(r["snr_db"])
            if s < SNR_FLOOR_DB:
                excluded += 1
                continue
            el.append(float(r["elevation_deg"]))
            az.append(float(r["azimuth_deg"]))
            snr.append(s)
            oid.append(r["obs_id"])
            decoded.append(r.get("decoded"))
    return (np.array(el), np.array(az), np.array(snr),
            np.array(oid), np.array(decoded), excluded)


el, az, snr_reported, obs_id, decoded, n_excluded = load()
print(f"Loaded {len(el):,} in-scope samples across {len(set(obs_id))} passes")
print(f"Excluded {n_excluded} samples below {SNR_FLOOR_DB} dB (recording dropouts)")

snr_true = correct_estimator_bias(snr_reported)
valid = ~np.isnan(snr_true)
el, az, snr_true, obs_id, decoded = (el[valid], az[valid], snr_true[valid],
                                      obs_id[valid], decoded[valid])
residual = snr_true - model_cn_db(el)

# Anchor residuals to their high-elevation ceiling, where obstruction is absent.
# This makes "0" mean unobstructed and negative mean loss, rather than carrying
# the arbitrary absolute calibration offset of the estimator.
ceiling = np.median(residual[el >= 60])
residual = residual - ceiling
print(f"Residual ceiling (median above 60 deg) removed: {ceiling:+.2f} dB")
print(f"Residual range: {residual.min():+.1f} to {residual.max():+.1f} dB")

# ---------------------------------------------------------------------------
# Bin
# ---------------------------------------------------------------------------
AZ_STEP, EL_STEP = 15, 5
MIN_SAMPLES = 20
az_edges = np.arange(0, 361, AZ_STEP)
el_edges = np.arange(5, 91, EL_STEP)

grid = np.full((len(az_edges) - 1, len(el_edges) - 1), np.nan)
count = np.zeros_like(grid)
for i in range(len(az_edges) - 1):
    in_az = (az >= az_edges[i]) & (az < az_edges[i + 1])
    for j in range(len(el_edges) - 1):
        m = in_az & (el >= el_edges[j]) & (el < el_edges[j + 1])
        count[i, j] = m.sum()
        if m.sum() >= MIN_SAMPLES:
            grid[i, j] = np.median(residual[m])

plt.rcParams.update({"figure.facecolor": "white", "axes.facecolor": "white",
                     "font.size": 10, "axes.grid": False})

# ---------------------------------------------------------------------------
# Figure 1 — residual sky map
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 5.5))
finite = grid[np.isfinite(grid)]
vmin, vmax = np.nanpercentile(finite, 2), np.nanpercentile(finite, 98)
lim = max(abs(vmin), abs(vmax))
mesh = ax.pcolormesh(az_edges, el_edges, grid.T,
                     cmap="RdYlBu_r", norm=TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim),
                     shading="flat")
cb = fig.colorbar(mesh, ax=ax, pad=0.02)
cb.set_label("Median residual vs link budget (dB)\nnegative = unmodelled loss")
ax.set_xlabel("Azimuth (degrees)")
ax.set_ylabel("Elevation (degrees)")
ax.set_title("B-Raspi sky map — measured SNR minus link-budget model\n"
             f"{len(el):,} samples, {len(set(obs_id))} Meteor passes")
ax.set_xticks(np.arange(0, 361, 45))
for a, lbl in [(0, "N"), (90, "E"), (180, "S"), (270, "W"), (360, "N")]:
    ax.text(a, 92, lbl, ha="center", fontsize=11, fontweight="bold")
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/skymap_residual.png", dpi=140)
print("wrote skymap_residual.png")

# ---------------------------------------------------------------------------
# Figure 2 — coverage
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(11, 5.5))
mesh = ax.pcolormesh(az_edges, el_edges, count.T, cmap="viridis", shading="flat")
fig.colorbar(mesh, ax=ax, pad=0.02).set_label("Samples per bin")
ax.set_xlabel("Azimuth (degrees)")
ax.set_ylabel("Elevation (degrees)")
ax.set_title("Sample coverage — bins below 20 samples are blank in the residual map")
ax.set_xticks(np.arange(0, 361, 45))
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/skymap_coverage.png", dpi=140)
print("wrote skymap_coverage.png")

# ---------------------------------------------------------------------------
# Figure 3 — horizon profile + failed passes
# ---------------------------------------------------------------------------
THRESH = -3.0
horizon = []
for i in range(len(az_edges) - 1):
    prof = grid[i]
    rec = np.nan
    for j in range(len(el_edges) - 1):
        if np.isfinite(prof[j]) and prof[j] > THRESH:
            rec = el_edges[j]
            break
    horizon.append(rec)
horizon = np.array(horizon, dtype=float)
az_centres = az_edges[:-1] + AZ_STEP / 2

fail_az, fail_el = [], []
for oid in set(obs_id[decoded == "0"]):
    m = obs_id == oid
    fail_el.append(el[m].max())
    fail_az.append(az[m][np.argmax(el[m])])

fig, ax = plt.subplots(figsize=(11, 5))
ax.fill_between(az_centres, 0, horizon, step="mid", alpha=0.35, color="#8b3a3a",
                label=f"Obstructed (residual < {THRESH:.0f} dB)")
ax.plot(az_centres, horizon, "o-", color="#8b3a3a", lw=1.8, ms=5,
        label="Recovery elevation")
ax.scatter(fail_az, fail_el, marker="x", s=70, color="#1f4e8c", linewidths=1.8,
           label=f"Failed passes ({len(fail_az)}), plotted at max elevation", zorder=5)
ax.set_xlabel("Azimuth (degrees)")
ax.set_ylabel("Elevation (degrees)")
ax.set_title("Derived horizon profile, with decode failures overlaid")
ax.set_xlim(0, 360); ax.set_ylim(0, 60)
ax.set_xticks(np.arange(0, 361, 45))
for a, lbl in [(0, "N"), (90, "E"), (180, "S"), (270, "W"), (360, "N")]:
    ax.text(a, 57, lbl, ha="center", fontsize=11, fontweight="bold")
ax.legend(loc="upper right", framealpha=0.92)
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/horizon_profile.png", dpi=140)
print("wrote horizon_profile.png")

# ---------------------------------------------------------------------------
# Figure 4 — SNR vs elevation coloured by azimuth
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(10, 6))
sc = ax.scatter(el, snr_true, c=az, cmap="twilight", s=2, alpha=0.35)
cb = fig.colorbar(sc, ax=ax, pad=0.02); cb.set_label("Azimuth (degrees)")
elc = np.linspace(5, 90, 200)
ax.plot(elc, model_cn_db(elc) + ceiling, color="k", lw=2, ls="--",
        label="Link-budget model (offset to data)")
ax.set_xlabel("Elevation (degrees)")
ax.set_ylabel("SNR, estimator bias corrected (dB)")
ax.set_title("SNR vs elevation, coloured by azimuth\n"
             "separation between branches indicates azimuthal asymmetry")
ax.legend(loc="lower right")
ax.grid(alpha=0.25)
fig.tight_layout()
fig.savefig(f"{OUT_DIR}/snr_elevation_by_azimuth.png", dpi=140)
print("wrote snr_elevation_by_azimuth.png")

# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------
SECTORS = [("N  (337-023)", lambda a: (a >= 337) | (a < 23)),
           ("NE (023-068)", lambda a: (a >= 23) & (a < 68)),
           ("E  (068-113)", lambda a: (a >= 68) & (a < 113)),
           ("SE (113-158)", lambda a: (a >= 113) & (a < 158)),
           ("S  (158-203)", lambda a: (a >= 158) & (a < 203)),
           ("SW (203-248)", lambda a: (a >= 203) & (a < 248)),
           ("W  (248-293)", lambda a: (a >= 248) & (a < 293)),
           ("NW (293-337)", lambda a: (a >= 293) & (a < 337))]

lines = ["B-Raspi sky map analysis", "=" * 64,
         f"Samples: {len(el):,}   Passes: {len(set(obs_id))}",
         f"Excluded below {SNR_FLOOR_DB} dB (recording dropouts): {n_excluded}",
         f"Estimator bias corrected via S/N = 10^(reported/10) - 1",
         f"Residual anchored to median above 60 deg ({ceiling:+.2f} dB removed)",
         "",
         "Median residual by sector and elevation band (dB):",
         f"  {'sector':<14} {'5-15':>8} {'15-25':>8} {'25-40':>8} {'40-60':>8} {'>60':>8}"]

bands = [(5, 15), (15, 25), (25, 40), (40, 60), (60, 90)]
for name, pred in SECTORS:
    sel = pred(az)
    row = f"  {name:<14}"
    for lo, hi in bands:
        m = sel & (el >= lo) & (el < hi)
        row += f" {np.median(residual[m]):8.2f}" if m.sum() >= MIN_SAMPLES else f" {'--':>8}"
    lines.append(row)

lines += ["", "Derived recovery elevation by azimuth (elevation at which residual",
          f"first exceeds {THRESH:.0f} dB; higher implies greater obstruction):"]
for a, h in zip(az_centres, horizon):
    lines.append(f"  {a:5.0f} deg : {('%.0f deg' % h) if np.isfinite(h) else 'no recovery in range'}")

lines += ["", f"Decode failures: {len(fail_az)} passes",
          "  max-elevation azimuth distribution:"]
fail_sect = defaultdict(int)
for a in fail_az:
    for name, pred in SECTORS:
        if pred(np.array([a]))[0]:
            fail_sect[name] += 1
for name, _ in SECTORS:
    lines.append(f"    {name:<14} {fail_sect.get(name, 0)}")

report = "\n".join(lines)
open(f"{OUT_DIR}/skymap_report.txt", "w").write(report + "\n")
print("\n" + report)
