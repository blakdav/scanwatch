#!/bin/bash
#
# Polls the scanner's ADF sensor. When paper appears, scans the whole stack
# and writes a PDF. Each stack is one document.
#
# In double-sided mode the first stack is held, and the next stack is treated
# as the reverse sides. The ADF reverses page order on output, so refeeding
# the output pile unchanged gives backs in reverse order. They are reversed
# back and interleaved with the fronts.

IP=${SCANNER_IP}
OUT=/out
STATE=/state/duplex
PEND=/state/pending
DEV="airscan:e0:brother"
MODE=${SCAN_MODE:-Gray}
RES=${SCAN_RESOLUTION:-300}
POLL=${POLL_INTERVAL:-2}

armed=1

adf_state() {
  curl -s --max-time 5 "http://$IP/eSCL/ScannerStatus" | grep -o 'ScannerAdf[A-Za-z]*'
}

stamp() {
  date +%Y%m%d-%H%M%S
}

while true; do
  st=$(adf_state)

  if [ "$st" = "ScannerAdfLoaded" ] && [ "$armed" = "1" ]; then
    d=$(mktemp -d)
    echo "paper detected, scanning"

    scanimage -d "$DEV" --source ADF --mode "$MODE" --resolution "$RES" \
      --format=jpeg --batch="$d/p%03d.jpg" 2>&1 | grep -v '^Scanning page' || true

    n=$(ls "$d"/*.jpg 2>/dev/null | wc -l)

    if [ "$n" -gt 0 ]; then
      if [ -f "$STATE" ]; then

        if [ ! -f "$PEND" ]; then
          f=$(mktemp -d)
          mv "$d"/*.jpg "$f"/
          echo "$f" > "$PEND"
          echo "held $n fronts, refeed the stack for the reverse sides"
        else
          f=$(cat "$PEND")
          rm -f "$PEND"
          mapfile -t fr < <(ls "$f"/*.jpg 2>/dev/null | sort)
          mapfile -t bk < <(ls "$d"/*.jpg 2>/dev/null | sort -r)

          if [ "${#bk[@]}" -ne "${#fr[@]}" ]; then
            echo "page count mismatch: ${#fr[@]} fronts, ${#bk[@]} backs. Writing both stacks separately"
            img2pdf "$f"/*.jpg -o "$OUT/scan-$(stamp)-fronts.pdf"
            img2pdf "$d"/*.jpg -o "$OUT/scan-$(stamp)-backs.pdf"
            rm -rf "$f"
          else
            m=$(mktemp -d)
            i=0
            while [ $i -lt ${#fr[@]} ]; do
              cp "${fr[$i]}" "$m/$(printf '%04d' $((i * 2))).jpg"
              cp "${bk[$i]}" "$m/$(printf '%04d' $((i * 2 + 1))).jpg"
              i=$((i + 1))
            done
            img2pdf "$m"/*.jpg -o "$OUT/scan-$(stamp).pdf"
            echo "wrote double-sided PDF, ${#fr[@]} sheets, $((${#fr[@]} * 2)) pages"
            rm -rf "$f" "$m"
          fi
        fi

      else
        img2pdf "$d"/*.jpg -o "$OUT/scan-$(stamp).pdf"
        echo "wrote PDF, $n pages"
      fi
    else
      echo "no pages captured"
    fi

    rm -rf "$d"
    armed=0
  fi

  if [ "$st" = "ScannerAdfEmpty" ]; then
    armed=1
  fi

  sleep "$POLL"
done
