#!/bin/bash
# Meteor LRPT IQ processor — watches for new IQ files and decodes with SatDump

IQ_DIR="/var/lib/docker-bindmounts/satnogs_satnogs-client/opt/satnogs-non-free"
OUTPUT_BASE="/home/brian/satdump_output"
STATION_ID=4621
API_TOKEN="Satnogs_Token_Here"
PROCESSED_LOG="/home/brian/.processed_iq_files"
MIN_SIZE_BYTES=104857600  # 100 MB minimum — rejects incomplete recordings

touch "$PROCESSED_LOG"
mkdir -p "$OUTPUT_BASE"

process_file() {
    local iq_file="$1"
    local basename=$(basename "$iq_file" .raw)
    local output_dir="$OUTPUT_BASE/$basename"

    echo "[$(date)] Processing: $iq_file"
    mkdir -p "$output_dir"

    # Run SatDump decode
    satdump legacy meteor_m2-x_lrpt baseband "$iq_file" "$output_dir" \
        --samplerate 160000 --baseband_format cs16

    # Note whether images were produced, but DON'T return early — we still want
    # to run SNR/elevation analysis on weak passes that failed to decode.
    local images=$(find "$output_dir" -name "*.png" 2>/dev/null)
    if [ -z "$images" ]; then
        echo "[$(date)] No images produced — signal may have been too weak (analysis will still run)"
    else
        echo "[$(date)] Images produced: $images"
    fi

    # --- Observation lookup (needed for BOTH analysis and upload) ---
    # Convert filename timestamp to ISO format for API query
    # Filename format: iq_cs16_2026-06-08T14-37-44.raw
    local raw_ts=$(echo "$basename" | sed 's/iq_cs16_//')
    local iso_ts=$(echo "$raw_ts" | sed 's/T\([0-9][0-9]\)-\([0-9][0-9]\)-\([0-9][0-9]\)/T\1:\2:\3/')
    local start_ts=$(date -u -d "$iso_ts UTC - 10 minutes" +"%Y-%m-%dT%H:%M:%S" 2>/dev/null)
    local end_ts=$(date -u -d "$iso_ts UTC + 15 minutes" +"%Y-%m-%dT%H:%M:%S" 2>/dev/null)

    echo "[$(date)] Looking up observation ID for timestamp: $iso_ts"

    # Query SatNOGS API for matching observation
    local obs_json=$(curl -s \
        "https://network.satnogs.org/api/observations/?ground_station=${STATION_ID}&start=${start_ts}&end=${end_ts}" \
        -H "Authorization: Token ${API_TOKEN}")
    local obs_json_file="${output_dir}/.obs_response.json"
    echo "$obs_json" > "$obs_json_file"
    local obs_id=$(echo "$obs_json" | python3 -c "
import sys, json
data = json.load(sys.stdin)
if data and len(data) > 0:
    print(data[0]['id'])
" 2>/dev/null)

    # --- SNR vs elevation analysis (runs for ALL passes, decoded or not) ---
    # Non-blocking: a failure here never affects image upload.
    echo "[$(date)] Running SNR/elevation analysis"
    /home/brian/analyse_pass.sh "$iq_file" "$output_dir" "$iso_ts" "$obs_json_file" \
        || echo "[$(date)] Analysis step failed (non-fatal)"

    # --- Image upload (only if we actually have images AND an observation ID) ---
    if [ -z "$images" ]; then
        echo "[$(date)] No images to upload — analysis complete, done"
        echo "$iq_file" >> "$PROCESSED_LOG"
        return 0
    fi

    if [ -z "$obs_id" ]; then
        echo "[$(date)] Could not find observation ID — images saved locally only"
        echo "$iq_file" >> "$PROCESSED_LOG"
        return 1
    fi

    echo "[$(date)] Found observation ID: $obs_id — uploading artifacts"
    # Rotate + upload every PNG; null-delimited so spaces/parens are safe
    find "$output_dir" -name "*.png" -print0 | while IFS= read -r -d '' img; do
        echo "[$(date)] Rotating 180°: $img"
        mogrify -rotate 180 "$img"
        clean=$(basename "$img" | tr -d '()' | tr ' ' '_')
        fname="data_${obs_id}_${clean}"
        echo "[$(date)] Copying to container: $fname"
        docker exec -i satnogs_satnogs-client sh -c \
            "cat > '/tmp/.satnogs/data/$fname'" < "$img"
    done

    echo "[$(date)] Done processing $iq_file"
    echo "$iq_file" >> "$PROCESSED_LOG"
}

echo "[$(date)] Watching $IQ_DIR for new IQ files..."

# Watch for new files using inotifywait
inotifywait -m -e close_write "$IQ_DIR" --format '%w%f' | while read new_file; do
    # Only process IQ files
    [[ "$new_file" == *iq_cs16*.raw ]] || continue

    # Check minimum size
    local_size=$(stat -c%s "$new_file" 2>/dev/null || echo 0)
    if [ "$local_size" -lt "$MIN_SIZE_BYTES" ]; then
        echo "[$(date)] File too small ($local_size bytes) — skipping: $new_file"
        continue
    fi

    # Check not already processed
    grep -qF "$new_file" "$PROCESSED_LOG" && continue

    process_file "$new_file"
done
