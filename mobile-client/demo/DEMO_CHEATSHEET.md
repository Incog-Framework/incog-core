# Incog Mobile Client — Demo Cheat-Sheet

A stealth app's success looks like *nothing happening on the phone*. You prove it works by
showing the **live log on a laptop** while the phone does the covert work. This sheet is your
turnkey run-book.

---

## Secret codes (type on the calculator, then press `=`)

| Code | Action |
|---|---|
| `271828` `=` | Opens Accessibility settings (to enable the Sentinel Engine) |
| `314159` `=` | Stand down — stops an active Ghost State session |

> These are placeholder codes. Change them in `CalculatorViewModel.kt`
> (`SECRET_UNLOCK_CODE`, `STAND_DOWN_CODE`) before any real use.

**Trigger gesture:** Volume **Down → Down → Up**, quickly (all three within ~2 seconds).

---

## Before the demo (do this once, off-stage)

1. Connect the phone to the laptop with a **data** USB cable; unlock it and accept the USB
   debugging prompt.
2. Open the calculator app once and make sure these are granted / on:
   - **Microphone**, **Location**, **Notifications** permissions (allow if prompted).
   - Accessibility service **"Calculator Gestures"** is ON (type `271828` `=` to jump to the
     settings screen).
3. Start the live log on the laptop (project this screen):
   ```powershell
   .\demo-logcat.ps1
   ```
   (From `mobile-client/demo/`. It auto-finds adb and streams the Sentinel + Ghost State logs.)
4. Do one dry-run trigger to confirm data flows, then stand down (`314159` `=`) and you're ready.

---

## The live demo (~60 seconds)

1. **"An ordinary calculator."** Do some real math on the phone. It looks and works completely
   normal — this is the disguise (plausible deniability).
2. **"The phone is locked; the app is hidden."** Lock the screen / put it in your pocket.
3. **"The user is in danger and can't look at the screen."** Do the **DDU gesture** blind
   (Volume Down, Down, Up). Nothing visible happens on the phone.
4. **Point to the laptop log.** Call out the lines as they appear:
   - `DDU trigger detected` — the hidden gesture was caught.
   - `Ghost State ACTIVATED — SessionID=... (mic=true, gps=true)` — covert session started.
   - `snapshot accel=... gyro=... loc=... audioRms=...` every 2s — **live accelerometer,
     gyroscope, GPS and microphone data being captured while the screen is off.**
   - Speak or move the phone: watch `audioRms` spike and the accel/GPS values change.
5. **Show the disguise.** Pull down the notification shade — it only says **"Calculator /
   Running"** with a calculator icon, and it's hidden from the lock screen entirely.
6. **"False alarm — stand down."** Type `314159` `=`. The log prints
   `Ghost State DEACTIVATED` — capture stops cleanly.

**The "wow" moment is step 4:** invisible, hands-free, screen-locked capture — the whole premise
of the project, proven live.

---

## What this demonstrates (map to the phases)

- **Phase 0** — functional calculator decoy (step 1)
- **Phase 1** — hidden hardware trigger, no screen interaction (step 3)
- **Phase 2** — covert Ghost State session + disguised notification (steps 4–5)
- **Phase 3** — live sensor + audio + GPS capture, even locked (step 4)

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `demo-logcat.ps1` says "no device" | Data cable, unlock phone, accept USB-debugging prompt |
| Trigger not detected | Press the three volume buttons faster (within ~2s) |
| No `mic=true`/`gps=true` | Re-grant Microphone/Location; reopen the app once |
| Accessibility toggle off | It only turns off after a **reinstall**; re-enable via `271828` `=` |
| Notification not showing | Grant the Notifications permission (reopen app once) |

---

## Talking points if asked

- **Volume popup during the gesture:** intentional. Consuming volume keys to hide it reliably
  breaks normal volume control, which is *more* suspicious than a brief popup during activation.
- **"Calculator" in the notification:** Android always shows the real app name and forbids
  spoofing it, so the most discreet option is a plain notification consistent with the calculator
  identity (not a fake "System" one).
- **Nothing leaves the phone yet:** evidence encryption, steganography, and backend upload are
  teammates' later phases; this module is the capture front-end.
