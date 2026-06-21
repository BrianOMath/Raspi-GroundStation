#!/bin/bash
# analyse_pass.sh — per-pass SNR vs elevation analysis
#
# Called by process_meteor.sh after a successful SatDump decode, while the
# raw IQ file is still present. Produces pass_analysis.csv in the pass's
# SatDump output folder (alongside telemetry.json, MSU-MR/, etc).
#
# Usage:
#   analyse_pass.sh <iq_file> <output_dir> <iso_ts> <obs_json_file>
#
#   iq_file       : full path to the raw cs16 IQ recording
#   output_dir    : the pass's SatDump output directory
#   iso_ts        : recording start timestamp, ISO (e.g. 2026-06-18T02:54:02)
#   obs_json_file : path to a file containing the SatNOGS API JSON response
#                   (so we reuse the lookup process_meteor.sh already did,
#                    rather than calling the API a second time)
#
# Exits non-zero on failure but is designed to be called such that a failure
# never blocks image upload in the parent script.

set -u

IQ_FILE="$1"
OUTPUT_DIR="$2"
ISO_TS="$3"
OBS_JSON_FILE="$4"

# SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
SCRIPT_DIR="/home/brian"
MASTER_CSV="/home/brian/satdump_output/all_passes_snr_elevation.csv"

SNR_TMP="${OUTPUT_DIR}/snr_trace_tmp.csv"
FINAL_CSV="${OUTPUT_DIR}/pass_analysis.csv"

log() { echo "[$(date)] [analyse_pass] $*"; }

# --- Extract TLE + station coords from the API response we already have ---
read_field() {
    python3 -c "
import sys, json
try:
    data = json.load(open('$OBS_JSON_FILE'))
    obs = data[0] if isinstance(data, list) and data else data
    val = obs.get('$1', '')
    print(val if val is not None else '')
except Exception:
    print('')
"
}

TLE0=$(read_field tle0)
TLE1=$(read_field tle1)
TLE2=$(read_field tle2)
LAT=$(read_field station_lat)
LON=$(read_field station_lng)
ALT=$(read_field station_alt)

if [ -z "$TLE1" ] || [ -z "$TLE2" ] || [ -z "$LAT" ] || [ -z "$LON" ]; then
    log "Missing TLE or station coords in API response — skipping analysis"
    exit 1
fi
[ -z "$ALT" ] && ALT=0
[ -z "$TLE0" ] && TLE0="SAT"

# --- Step 1: SNR trace from the raw IQ ---
log "Computing SNR trace from $IQ_FILE"
python3 "${SCRIPT_DIR}/iq_snr_trace.py" "$IQ_FILE" "$SNR_TMP"
if [ $? -ne 0 ] || [ ! -f "$SNR_TMP" ]; then
    log "SNR trace step failed — skipping analysis"
    exit 1
fi

# --- Step 2: correlate each SNR sample with elevation/azimuth ---
log "Correlating SNR with elevation (TLE epoch from API, station ${LAT},${LON})"
python3 "${SCRIPT_DIR}/correlate_snr_elevation.py" "$SNR_TMP" "$FINAL_CSV" \
    --tle0 "$TLE0" --tle1 "$TLE1" --tle2 "$TLE2" \
    --lat "$LAT" --lon "$LON" --alt "$ALT" \
    --start "${ISO_TS}Z"
if [ $? -ne 0 ] || [ ! -f "$FINAL_CSV" ]; then
    log "Elevation correlation step failed — skipping analysis"
    rm -f "$SNR_TMP"
    exit 1
fi

rm -f "$SNR_TMP"
log "Wrote $FINAL_CSV"

# --- Step 3: append to master aggregate CSV (one row per second, all passes) ---
OBS_ID=$(read_field id)
[ -z "$OBS_ID" ] && OBS_ID="unknown"

if [ ! -f "$MASTER_CSV" ]; then
    echo "obs_id,elapsed_seconds,utc_time,elevation_deg,azimuth_deg,snr_db" > "$MASTER_CSV"
fi
# skip the per-pass header line, prefix each row with obs_id
tail -n +2 "$FINAL_CSV" | while IFS= read -r line; do
    echo "${OBS_ID},${line}"
done >> "$MASTER_CSV"
log "Appended $(tail -n +2 "$FINAL_CSV" | wc -l) rows to master CSV for obs $OBS_ID"

exit 0