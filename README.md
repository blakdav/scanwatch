# scanwatch

Turns a plain network scanner into a scan-to-Paperless appliance. Load paper in
the document feeder and walk away. A PDF appears in the consume directory.

No vendor drivers, no cloud service, no computer involved at scan time. The
scanner is driven over eSCL, the vendor-neutral driverless scanning protocol
also known as AirScan.

## How it works

`scanwatch` polls the scanner's `ScannerStatus` endpoint. When the feeder
sensor reports paper, it scans the whole stack, assembles the pages into a
PDF, and writes it to the output directory.

One stack is one document. Feed several stacks back to back and you get
several PDFs, so documents stay separated without any sorting afterwards.

## Double-sided pages

The feeder is single-sided, so both sides take two passes. Turn on
double-sided mode in the web interface and it stays on until you turn it off.

1. Feed the stack. The front sides are held.
2. Take the output pile and put it straight back in. Do not reorder it.
3. The two passes are merged into one PDF with the pages in the right order.

The feeder reverses page order on output, so the reverse sides arrive backwards.
`scanwatch` accounts for that. If the two passes have different page counts it
writes them as two separate PDFs rather than producing a scrambled document.

Turning the mode off discards any held front sides, so a forgotten toggle
cannot silently pair unrelated stacks.

## Paper size

Pick the size in the web interface. The feeder does not auto crop, so a page
scanned at the wrong setting either gets blank space below it or loses the
bottom of the page. Letter, A4, Legal, A5 and receipt widths are available.

## Resolution

Set it in the web interface. 300 dpi suits general documents and is what OCR
wants. 600 dpi is available for fine print or photographs, at roughly four
times the file size. A custom value can be entered, but the scanner will fall
back to the nearest resolution it actually supports.

`scanwatch` reads the supported values from the scanner on startup and shows
the real ceiling for your hardware in the interface. A Brother DCP-L2550DW
offers 100, 200, 300 and 600 dpi over eSCL. The sensor is capable of more, but
the driverless protocol does not expose it.

## Pausing

Polling keeps a short conversation going with the scanner, which on some
printers prevents them reaching their deepest sleep state. The watch toggle
stops the polling entirely so the printer is left alone, and you turn it back
on when you want to scan. Leave it running unless you find your printer will
not sleep.

## Requirements

An eSCL capable scanner with a document feeder, reachable over the network at
a fixed address. Check yours with:

```
curl -s http://SCANNER_IP/eSCL/ScannerCapabilities
```

XML in response means you are good. Look for an `AdfSimplexInputCaps` section
to confirm the feeder is exposed, and for `DetectPaperLoaded` in `AdfOptions`
to confirm the sensor can be polled.

Verified on a Brother DCP-L2550DW.

## Running it

```yaml
services:
  ScanWatch:
    image: ghcr.io/blakdav/scanwatch:latest
    container_name: ScanWatch
    restart: unless-stopped
    environment:
      SCANNER_IP: 172.23.24.78
    volumes:
      - /opt/docker/paperless/consume:/out
      - /opt/docker/scanwatch/state:/state
    ports:
      - "8080:8080"
```

Then open port 8080 in a browser for the double-sided toggle and a live
activity log.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `SCANNER_IP` | required | Address of the scanner |
| `PUID` / `PGID` | `1000` | Ownership of the written PDFs |
| `TZ` | `UTC` | Timezone for log timestamps and PDF filenames |

Set `PUID` and `PGID` to match whatever Paperless runs as, or it will not be
able to read the files.

Everything else is set in the web interface: paper size, colour, resolution,
the check interval, double-sided mode and whether the watcher is running.

## Notes

The container declares the scanner statically and disables discovery, because
Avahi is not available inside a container and `sane-airscan` will not
initialise without one or the other.

Anything loaded into the feeder gets scanned, including paper you put there
for some other reason. There is no grace period.

All settings live in `/state`, so they survive a restart. Delete a file from
that directory to put the corresponding setting back to its default.

## File names

PDFs are named `2026-09-10_2214.pdf`. Year first means the folder sorts
chronologically on its own. Two stacks scanned in the same minute get `_2`,
`_3` and so on appended rather than overwriting each other.

## Logging

The web interface shows the last 100 actions. The same lines go to the
container log, so `docker compose logs -f` works as well. Nothing is written
to disk.

## License

MIT
