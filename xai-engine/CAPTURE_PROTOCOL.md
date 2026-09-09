# Capture protocol — teaching the model to detect fleeing, not just not-suppress it

**For Aarush.** The GPS-suppression bug is fixed (`GPSVelocity` is now neutral, not
predictive — see `MODEL_CARD.md`), but that only stops the model working *against* a
fleeing scenario. Actually detecting one needs real captures where motion, audio and GPS
are observed *together*, which no public corpus provides. This is that capture plan.

## Why the design looks like this

Every scenario below is deliberately labeled by **what actually happened**, not by any
single sensor reading — because "high GPS ⇒ label it Emergency" is exactly the shortcut
that caused the bug we just fixed. If normal fast movement (jogging, being driven) isn't
captured as often as fleeing is, the model will just learn a new version of the same
mistake. So: **every motion/GPS level needs to appear in both classes.** Same logic for
audio — capture some loud *normal* audio (laughing, excited talking) so "loud ⇒
Emergency" doesn't become the next spurious shortcut.

## Setup (same for every run)

- **Phone placement: front trouser pocket, screen off**, mic-side unobstructed — this is
  the deployment condition, so it's the only placement worth capturing. If you also want
  a bag/hand comparison, label those separately (see `data/raw/sensor_packets/README` —
  ask me to add a placement field to the schema if you want that tracked; not required
  for this pass).
- **Do this somewhere private.** Sprinting and shouting for help in public will alarm
  bystanders and possibly bring a real emergency response. A garden, empty parking lot,
  or a long hallway/stairwell works for the "distress" scenarios; normal ones can be a
  regular walk/jog/drive.
- **Get a GPS fix before recording motion.** Start outside (or by a window), wait for
  `latestLocation` to populate in your logs, then begin the scenario. An indoor run with
  no fix records `GPSVelocity = 0` regardless of actual speed and is useless for this
  purpose — that's a *normal-stationary* capture, not a *normal-fast* one.
- **Each run: ≥45 continuous seconds.** The phone's history buffer is a rolling ~20 s
  window scored every 2 s (`SensorCollector.MAX_SAMPLES`, `GhostStateService.
  SNAPSHOT_INTERVAL_MS`). A 45–60 s run gives ~13–20 overlapping windows once the buffer
  fills, instead of just 1–2 from a 20 s clip.
- **Export every run as its own file** (one `SensorPacket` array per run — see
  "Where these go" below), so a bad run can be dropped without touching the others.

## Scenarios

| # | Scenario | Label | Motion | GPS | Audio | Duration | Runs |
|---|---|---|---|---|---|---|---|
| 1 | Brisk walk, calm | Normal | moderate | ~1.5–2 m/s | quiet/calm talk | 60s | 3 |
| 2 | Jog / run, calm | Normal | high | ~2.5–4 m/s | quiet/heavy breathing only | 60s | 3 |
| 3 | Car/bike passenger | Normal | low (body still) | ~5–15 m/s | quiet/normal talk | 60s | 2 |
| 4 | Loud but fine (laughing, excited talk), stationary | Normal | low | 0 m/s | **loud** | 45s | 2 |
| 5 | **Fleeing**: brisk walk away + calling for help / panicked talk | **Emergency** | moderate | ~1.5–2 m/s | **distress** | 60s | 3 |
| 6 | **Fleeing**: sprint away + panicked/shouting | **Emergency** | high | ~2.5–4 m/s+ | **distress** | 60s | 3 |
| 7 | **Distress, not fleeing**: shouting for help while stationary | **Emergency** | low | 0 m/s | **distress** | 45s | 2 |

**18 runs, ~16 minutes of recording**, plus setup/GPS-lock time — realistically a
30–40 minute session. Scenario 7 is the audio-shortcut guard (loud+distress+stationary
must not need motion to register); scenario 4 is its mirror (loud+calm+stationary must
not register as Emergency).

**Optional, if time allows — not required for this pass:** a brief (5–10s) violent
shake/struggle before scenario 5 or 6, to start covering Aarush's "struggle" emergency
variant too. Keep it as a separate labeled run if you do it, don't blend it into a
fleeing run — one variable changing per run is what makes the labels trustworthy.

## Where these go, and how to check them before trusting them

```
data/real_packets/normal/*.json          scenarios 1-4, one file per run
data/real_packets/emergency/*.json       scenarios 5-7, one file per run
```

Then, from `xai-engine/`:

```bash
python phase4/test_real_packets.py        # schema + sanity diagnostics first
```

This checks sample rate (~50 Hz), window length, timestamp monotonicity, and flags a
flat-zero `audioRmsEnergy` across every packet — which would mean the mic permission was
silently denied for that whole session (Aarush: this is the same flat-0.0 issue you're
chasing separately; if it shows up here, that session's audio is unusable, not the
capture protocol's fault).

**Blocker to close first, if not already:** `SensorPacket` needs a JSON export path
(`Json.encodeToString(packet)` written to a file during Ghost State, default property
names, no `@SerialName` renames — see `INTEGRATION.md` "Blocker" for the exact ask, this
predates the current fix and may already be resolved on your side).

Once captures pass validation, symlink or copy the same files into:

```
data/raw/sensor_packets/normal/*.json
data/raw/sensor_packets/emergency/*.json
```

(`INTEGRATION.md` explains why validating and training are kept as separate copies —
short version: it's deliberate, not duplication for its own sake.)

```bash
python phase5/dataset_adapters.py                                   # confirm visibility
python phase5/train_tflite_model.py --dataset sensor_packets         # real captures alone
python phase5/train_tflite_model.py --dataset fusion,sensor_packets  # combined with the existing fusion set — ask me first, this needs a small loader change to merge the two shapes
```

I'll take it from there once files land — running the full retrain, honest evaluation,
and updated `MODEL_CARD.md`.
