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
PAPER=/state/paper
PAUSED=/state/paused
RESFILE=/state/resolution
POLLFILE=/state/poll
DEV="airscan:e0:brother"
MODEFILE=/state/mode
DEFAULT_RES=300
DEFAULT_POLL=2

armed=1
was_paused=0

adf_state() {
  curl -s --max-time 5 "http://$IP/eSCL/ScannerStatus" | grep -o 'ScannerAdf[A-Za-z]*'
}

stamp() {
  date +%Y%m%d-%H%M%S
}

# Settings below are read fresh each pass so the web interface can change
# them without a restart.
current_res() {
  local v
  [ -f "$RESFILE" ] && v=$(cat "$RESFILE")
  case "$v" in
    ''|*[!0-9]*) echo "$DEFAULT_RES" ;;
    *) echo "$v" ;;
  esac
}

current_mode() {
  local v
  [ -f "$MODEFILE" ] && v=$(cat "$MODEFILE")
  case "$v" in
    Gray|Color|Lineart) echo "$v" ;;
    *) echo "Gray" ;;
  esac
}

current_poll() {
  local v
  [ -f "$POLLFILE" ] && v=$(cat "$POLLFILE")
  case "$v" in
    ''|*[!0-9.]*) echo "$DEFAULT_POLL" ;;
    *) echo "$v" ;;
  esac
}

# Page dimensions in millimetres, written by the web interface.
paper_dims() {
  local size="letter"
  [ -f "$PAPER" ] && size=$(cat "$PAPER")
  case "$size" in
    a4)     echo "210 297" ;;
    legal)  echo "215.9 355.6" ;;
    a5)     echo "148 210" ;;
    receipt) echo "80 297" ;;
    *)      echo "215.9 279.4" ;;
  esac
}

while true; do

  if [ -f "$PAUSED" ]; then
    if [ "$was_paused" = "0" ]; then
      echo "polling paused, the scanner is not being contacted"
      was_paused=1
    fi
    sleep "$(current_poll)"
    continue
  fi

  if [ "$was_paused" = "1" ]; then
    echo "polling resumed"
    was_paused=0
    armed=1
  fi

  st=$(adf_state)

  if [ "$st" = "ScannerAdfLoaded" ] && [ "$armed" = "1" ]; then
    read -r W H <<< "$(paper_dims)"
    RES=$(current_res)
    MODE=$(current_mode)
    d=$(mktemp -d)
    echo "paper detected, scanning at ${W}x${H}mm, ${RES} dpi, ${MODE}"

    scanimage -d "$DEV" --source ADF --mode "$MODE" --resolution "$RES" \
      -x "$W" -y "$H" \
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

  sleep "$(current_poll)"
done
