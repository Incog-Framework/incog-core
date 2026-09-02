# mobile-client — Aarush's scope (Phases 0–3)

Native Android Kotlin app. This is the calculator decoy + hidden trigger + Ghost State sensor
collection. Nothing here should require touching the other three module folders — this file plus
the workflow below is meant to be sufficient context on its own.

## Progress

- **Phase 0 (calculator decoy): DONE & on-device verified.** `calculator/` package — Compose UI,
  `CalculatorViewModel` (pure arithmetic, 10 unit tests passing), dark theme-independent look.
- **Phase 1 (Sentinel Engine): DONE & on-device verified.** `sentinel/` package —
  `SentinelAccessibilityService` detects the DDU volume pattern (Down-Down-Up within 2s), emits
  `TriggerEvent` on `SentinelBus` (the Phase 1→2 seam). Concealed onboarding: typing the secret
  code **`271828`** then `=` on the calculator opens Accessibility settings (an app can't enable
  its own accessibility service). Service is passive — it never consumes volume events (see note
  below), so normal volume control is unaffected.
- **Phase 2 (Ghost State): DONE & on-device verified.** `ghost/GhostStateService` — foreground
  service started by the Sentinel on DDU. Disguised notification: "Calculator / Running", a custom
  calculator vector icon (`res/drawable/ic_calc_notification.xml`), `VISIBILITY_SECRET` (hidden
  from lock screen), silent, `IMPORTANCE_MIN`. Re-triggering re-posts the notification if
  dismissed; a stand-down code **`314159`** + `=` stops the session. Notes: (1) Android always
  shows the real app name ("Calculator") in the notification header — cannot be spoofed, so the
  disguise is Calculator-consistent, not fake-system. (2) `POST_NOTIFICATIONS` is requested at
  launch (MainActivity); without it the FGS notification is silently suppressed. (3) The
  accessibility toggle only needs re-enabling after a reinstall (dev artifact), not in normal use.
- **Phase 3 (sensors/audio): DONE & on-device verified, incl. locked screen.** `sensors/` package
  — `SensorCollector` (accelerometer + gyroscope, bounded 1000-sample history),
  `LocationCollector` (FusedLocationProviderClient GPS), `AudioBufferCollector` (AudioRecord →
  30s in-memory circular PCM buffer, never hits disk; exposes rolling RMS). Started/stopped by
  `GhostStateService`; a 2s snapshot logger prints live values. FGS type is chosen at runtime from
  granted permissions (microphone|location|dataSync fallback). Mic + fine/coarse location
  requested at launch (MainActivity). **Critical result: starting the mic+location FGS from the
  LOCKED screen worked on the OnePlus 11R — audio RMS responded to real sound and GPS kept
  updating while locked, so the "Display over other apps" exemption was NOT needed.** Uses
  `play-services-location` (added to the version catalog + app build.gradle).
- **All of Aarush's assigned scope (Phases 0–3) is complete and validated end-to-end on device.**

### Remaining seam: Phase 3 -> Phase 4 handoff (cross-team, not solo)
`handoff/SensorPacket.kt` is the producer-side contract (built every 2s in
`GhostStateService.buildSensorPacket()`, currently only logged). Wiring it to actually feed
Lipika's `xai-engine` (Phase 4 feature extraction) requires her module to exist — that's a
cross-team integration step. Keep `SensorPacket`'s shape stable until then.

### Key decision: volume-key handling
The Sentinel Engine does NOT consume/intercept volume events (`onKeyEvent` always returns false).
An earlier version consumed rapid-sequence events to hide the volume popup, but consuming a key's
UP while passing its DOWN made Android think the button was stuck (popup stayed up, volume broke).
Passive detection is the deliberate choice: normal volume works perfectly; the only cost is the
volume popup flicks briefly during the DDU gesture itself (harmless in an emergency).

## Build environment (Windows, this machine — important gotchas)

- **No `JAVA_HOME` on PATH.** Command-line Gradle needs it set to Android Studio's bundled JDK:
  `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"`.
- **Build output is redirected OUT of the OneDrive-synced tree.** The project lives under
  `OneDrive\Desktop`, and OneDrive locks files inside `build/` mid-build → "Unable to delete
  directory" failures. `build.gradle.kts` redirects `layout.buildDirectory` to
  `C:\AndroidBuilds\incog-mobile-client\<module>`. Debug APK ends up at
  `C:\AndroidBuilds\incog-mobile-client\app\outputs\apk\debug\app-debug.apk`.
- **adb** is at `%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe`. Test device: OnePlus (CPH2487)
  over USB.
- **Low-RAM machine (8 GB).** Running command-line Gradle while Android Studio is open can OOM-kill
  the Gradle daemon. For quick installs prefer: `gradlew assembleDebug` (CLI) then
  `adb install -r <apk>` (lightweight) rather than `installDebug`. On-device UI runs are usually
  done by the user via Android Studio's Run button.

## Recommended stack

- **Kotlin, native Android** (not Flutter) — the core requirement (system-wide volume-key
  interception via `AccessibilityService`, working with screen locked / app backgrounded) is a
  native-only API; a Flutter shell would just add a platform-channel bridge around code that has
  to be native anyway.
- **UI:** Jetpack Compose for the calculator decoy.
- **Sentinel Engine:** `AccessibilityService`, `FLAG_REQUEST_FILTER_KEY_EVENTS`, override
  `onKeyEvent()` to catch + consume `KEYCODE_VOLUME_DOWN` / `KEYCODE_VOLUME_UP`, validate DDU
  timing window.
- **Sensors:** `SensorManager` (accelerometer, gyroscope), `FusedLocationProviderClient` (GPS).
- **Audio:** `AudioRecord` into a circular in-memory buffer (not `MediaRecorder` to disk — nothing
  should hit storage until it's actually needed downstream).
- **Known risk to spike early:** Android 9+ (and esp. 14+ with `FOREGROUND_SERVICE_MICROPHONE` /
  `FOREGROUND_SERVICE_LOCATION` types) requires a persistent notification for background mic/GPS
  access. This is in tension with the "zero visible indicator" Ghost State goal — test what the
  minimum-visibility notification can look like before building deep into Phase 2/3.

## Your phases

| Phase | You build | Output |
|---|---|---|
| 0 | Calculator UI (Compose); Sentinel Engine listens in background | normal calc app; background listener armed |
| 1 | DDU volume pattern detection + timing validation; suppress system volume popup | Trigger Event `{trigger, timestamp, triggerType}` |
| 2 | Ghost State: background thread, zero visible UI, start sensors + circular audio buffer | `SensorSessionID` |
| 3 | Live sensor + audio collection loop | Sensor Packet + Audio Stream |

## Handoff to Lipika (Phase 3 → Phase 4) — the contract you must not break

Your output feeds directly into her sensor-fusion/feature-extraction step. Deliver:
- Raw sensor arrays (accelerometer, gyroscope, GPS) as JSON or a serializable data class,
  timestamped so she can synchronize across sensors.
- The live audio buffer as a stream/reference she can consume (not necessarily a finished file —
  Phase 3 is "Live Audio Memory Stream", the file gets flushed later at Phase 7 by Gagan).

Keep this shape stable even as you iterate on internals — Lipika's `xai-engine` code depends on
it. If you need to change the schema, that's a cross-team conversation, not a unilateral change.

## Not your scope (context only, don't build)

Phases 4–12 (feature extraction, TFLite inference, encryption, steganography, backend, SOS
dispatch) belong to Lipika, Gagan, and Chirag respectively. Full pipeline detail is in
`../../CLAUDE.md` if you ever need it, but day to day you shouldn't need to load it.
