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
announced=0

adf_state() {
  curl -s --max-time 5 "http://$IP/eSCL/ScannerStatus" | grep -o 'ScannerAdf[A-Za-z]*'
}

stamp() {
  date +%Y-%m-%d_%H%M
}

# Two stacks fed inside the same minute would collide, so add a suffix.
unique_name() {
  local base
  base=$(stamp)
  if [ ! -e "$OUT/$base.pdf" ]; then
    echo "$base"
    return
  fi
  local n=2
  while [ -e "$OUT/${base}_$n.pdf" ]; do
    n=$((n + 1))
  done
  echo "${base}_$n"
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

  if [ "$announced" = "0" ] && [ -n "$st" ]; then
    echo "ready. Load a stack in the feeder to scan"
    announced=1
  fi

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
            base=$(stamp)
            img2pdf "$f"/*.jpg -o "$OUT/${base}_fronts.pdf"
            img2pdf "$d"/*.jpg -o "$OUT/${base}_backs.pdf"
            echo "saved ${base}_fronts.pdf and ${base}_backs.pdf separately"
            rm -rf "$f"
          else
            m=$(mktemp -d)
            i=0
            while [ $i -lt ${#fr[@]} ]; do
              cp "${fr[$i]}" "$m/$(printf '%04d' $((i * 2))).jpg"
              cp "${bk[$i]}" "$m/$(printf '%04d' $((i * 2 + 1))).jpg"
              i=$((i + 1))
            done
            name=$(unique_name)
            img2pdf "$m"/*.jpg -o "$OUT/$name.pdf"
            echo "saved $name.pdf, ${#fr[@]} sheets scanned on both sides, $((${#fr[@]} * 2)) pages"
            rm -rf "$f" "$m"
          fi
        fi

      else
        name=$(unique_name)
        img2pdf "$d"/*.jpg -o "$OUT/$name.pdf"
        echo "saved $name.pdf, $n pages"
      fi
    else
      echo "no pages captured"
    fi

    rm -rf "$d"
    armed=0
  fi

  if [ "$st" = "ScannerAdfEmpty" ] && [ "$armed" = "0" ]; then
    armed=1
    if [ -f "$PEND" ]; then
      echo "ready. The next stack will be the reverse sides of the document being held"
    else
      echo "ready. The next stack will start a new document"
    fi
  fi

  sleep "$(current_poll)"
done
