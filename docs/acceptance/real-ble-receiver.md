# Real BLE Receiver Acceptance Checklist

- [ ] tri-timing receiver-run --help shows receiver options.
- [ ] Receiver can start with fixture race and athlete files.
- [ ] Valid iBeacon manufacturer data parses into UUID/major/minor.
- [ ] Known beacons are written to local JSONL before upload.
- [ ] Unknown beacons are ignored for race timing and counted in health.
- [ ] POST /api/detections stores known raw detections.
- [ ] Live detections can advance the expected route event.
- [ ] Pre-start detections do not advance route state.
- [ ] Admin UI shows receiver health and latest known beacon RSSI.
- [ ] Receiver continues logging locally if upload fails.
- [ ] Manual hardware walk/run test captures packets within roughly 5m.
