# data/real_packets/ — real captures from the device (never committed)

Everything here except this README is gitignored. Drop Aarush's exported
Ghost State captures in and the pipeline + tests pick them up with no code
changes.

## Layout

```
data/real_packets/
  normal/*.json        everyday activity — walking, pocket, bag, stairs, desk
  emergency/*.json     staged incidents
  *.json               unsorted captures are still validated, but cannot be
                       used for training until sorted
```

The folder name supplies the label. Each file is one `SensorPacket` JSON
object, or an array of them (a session export is naturally an array — the
phone builds one packet every 2 s).

## Check what arrived

```
python phase4/test_real_packets.py
```

Reports schema validity, feature ranges, and diagnostics: estimated sample
rate, window length, timestamp monotonicity, and whether `AudioEnergy` is
flat zero (which would mean the mic permission was denied).

## Run one through the pipeline

```
python run_ai_pipeline.py --packet data/real_packets/emergency/fall_01.json
```

See `../../INTEGRATION.md` for the full runbook.
