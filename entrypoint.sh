#!/bin/bash
set -e

if [ -z "$SCANNER_IP" ]; then
  echo "SCANNER_IP is not set. Set it to the scanner's address, for example 172.23.24.78"
  exit 1
fi

# Avahi is not available in the container, so discovery is disabled and the
# device is declared statically. sane-airscan aborts init without this.
cat > /etc/sane.d/airscan.conf <<CONF
[devices]
brother = http://${SCANNER_IP}/eSCL/, escl

[options]
discovery = disable
CONF

mkdir -p /state /out

if ! getent group scanwatch >/dev/null; then
  groupadd -g "$PGID" scanwatch 2>/dev/null || groupadd scanwatch
fi
if ! getent passwd scanwatch >/dev/null; then
  useradd -u "$PUID" -g "$PGID" -M -s /usr/sbin/nologin scanwatch 2>/dev/null || \
    useradd -g scanwatch -M -s /usr/sbin/nologin scanwatch
fi

chown -R "$PUID:$PGID" /state /app

echo "scanwatch starting, scanner at ${SCANNER_IP}, writing to /out"

exec gosu "$PUID:$PGID" python3 /app/app.py
