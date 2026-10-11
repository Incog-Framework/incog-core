# Incog — Installing the app (sideload)

The app is distributed as a **signed APK** that installs as an ordinary-looking **"Calculator."**
It is not on the Play Store (an app using `SEND_SMS` + accessibility + background mic + a disguise
needs Play policy sign-off), so it's installed by **sideloading**.

- **File:** `incog-calculator-release.apk` (~22 MB)
- **Current version:** 1.1 (`versionCode` 2) — SMS-permission UX + false-alarm safeguards
- **App id / label:** `com.incog.mobileclient` / "Calculator"
- **Min Android:** 8.0 (API 26)

> Check which version a phone has: **Settings → Apps → Calculator** — it should read **1.1**.
> Every distributed build bumps `versionCode`/`versionName`, so this is the quickest way to tell
> whether someone is testing the current APK before you debug anything they report.

---

## 1. How it's signed & verified

The APK is signed with the project's **release key** (self-signed):

```
Signer: CN=Incog, OU=CSBS, O=BMSCE, L=Bengaluru, ST=Karnataka, C=IN
SHA-256: adb2fa6592eca1f303bd52a1a080bd1c288d243dd899b2e4b42d5974604989e8
```

Anyone can verify a copy they received is authentic (unmodified, from this key):

```powershell
# needs Android build-tools + JAVA_HOME set
apksigner verify --print-certs incog-calculator-release.apk
```

The printed SHA-256 must match the digest above. What the signature guarantees:
- **Integrity** — the APK wasn't tampered with after signing.
- **Consistent updates** — only APKs signed with the *same* key can update an install.

It does **not** mean a third party (Google/a CA) vouched for it — it's self-signed. So **Play Protect
will warn on install** ("unsafe app"); that's expected for a sideloaded app with these permissions.

> ⚠️ Keep the keystore (`mobile-client/incog-release.jks`, gitignored) safe. Lose it and you can
> never ship a signed update to anyone who already installed this — they'd have to uninstall/reinstall.

---

## 2A. Install on YOUR phone (which has the debug build) — via USB/adb

The debug and release builds are signed with **different keys**, so you must remove the debug app
first (this clears its setup/contacts):

```powershell
$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
& $adb uninstall com.incog.mobileclient          # remove the debug build
& $adb install incog-calculator-release.apk       # install the signed release
```

("App not installed" / "signatures do not match" almost always means an existing install with a
different key — uninstall it first.)

## 2B. Install on SOMEONE ELSE's phone — sideload (no computer needed)

1. **Get the APK onto the phone** — share it via Google Drive / WhatsApp / email, or copy over USB.
2. **Tap the APK file.** Android blocks it the first time — tap the prompt and **allow "Install
   unknown apps"** for the app you opened it from (Files, Chrome, WhatsApp…), then tap the APK again.
3. **Install.** If **Play Protect** warns, choose **"More details → Install anyway."**
4. Done — a "Calculator" icon appears.

## 2C. UPDATING an existing install (already has an older Incog)

The release key never changes, so a newer APK **installs straight over the old one and keeps the
existing setup** — name, trusted contacts, codes and the encrypted config all survive. There is no
need to uninstall, and uninstalling would wipe the setup, so don't.

Just open the new APK and tap **Update**.

**Tell whoever you send it to about these three changes, or they will report them as bugs:**

1. **Re-enable "Calculator Gestures" after updating.** Updating the app unbinds the accessibility
   service, so the DDU gesture silently stops working until it's turned back on: type your **unlock
   code** then `=` → toggle **Calculator Gestures** off and back on. This is the single most common
   reason an updated install looks "dead".
2. **The phone now vibrates once when a session starts, and once when it stands down.** That is
   deliberate — a trigger used to be completely imperceptible, so an *accidental* one could reach
   your contacts without you ever knowing. The buzz is what lets you catch it. It can be switched
   off in setup ("Vibrate on trigger") if you need the trigger to leave no trace at all.
3. **Alerts now wait ~10 seconds before texting anyone.** When an emergency is detected, there is a
   grace window in which typing your **stand-down code** cancels the whole alert — no SMS, no
   upload. Do nothing and the alert sends as normal, so forgetting about it never costs you an
   alert. The delay is configurable in setup ("Alert delay"); `0` texts immediately.

---

## 3. First-run setup (every new install)

1. Open **Calculator** → the **setup screen** appears.
2. Enter **Your name** (shown to contacts in the alert), add **trusted contact(s)** (phone with
   country code), and set your three **codes** (unlock / stand-down / settings). Finish.
3. Grant permissions when prompted: **Microphone, Location, Notifications, SMS.**
4. Enable the trigger: type your **unlock code** then `=` → turn on **"Calculator Gestures"** in
   Accessibility → back out.

It now behaves as a normal calculator; the hidden safety features are armed.

---

## 4. Confirm it installed correctly

- The app opens and **works as a real calculator** (do some math).
- After setup, the **DDU gesture** (Volume Down-Down-Up) starts a covert session (visible only in
  logs / by the disguised "Calculator / Running" notification), and your **stand-down code** ends it.
- On a real trigger, your trusted contact(s) receive an **SMS** with a Google-Maps location link.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| "App not installed" / "signatures don't match" | An install with a different key exists — **uninstall it first** (`adb uninstall com.incog.mobileclient`). |
| Play Protect blocks it | Expected for sideload — "More details → Install anyway." |
| Install option greyed out | Enable "Install unknown apps" for the source app (Settings → Apps → Special access). |
| SMS never sends | Grant the **SMS** permission (Settings → Apps → Calculator → Permissions). |
| Trigger does nothing | Re-enable **"Calculator Gestures"** in Accessibility (turns off after a reinstall). |
| Trigger does nothing **after an app update** | Updating unbinds the accessibility service. Toggle **Calculator Gestures** OFF and back ON (unlock code → `=`). Verified cause, not a guess. |
| No vibration on trigger | Check **"Vibrate on trigger"** is on in setup. If it's on but feels faint, raise **Settings → Sound & vibration → Vibration intensity** — a system cap the app can't override. |
| Contacts got no SMS, but nothing seemed wrong | If you typed your stand-down code within the alert delay, the alert was **cancelled by design**. Check the "Alert delay" setting. |
| **"Restricted setting"** when enabling Calculator Gestures | Android 13+ blocks sideloaded apps from turning on Accessibility. Fix: **Settings → Apps → Calculator → ⋮ (top-right) → "Allow restricted settings"** → confirm, then enable the service. One-time, per phone. |
| Nothing on screen after the gesture | That's by design — it's covert; check the disguised notification or the logs. |

---

## 6. Before wider distribution (not yet done)

- **The backend URL and both keys are still compiled into the APK** and readable by anyone who
  decompiles it. The keys *have* been rotated once (the originals leaked via git history and are
  dead), but rotation doesn't change the structural problem: whoever holds the APK holds the
  credentials. Fine for a trusted pilot — **not** fine for public posting.
  > ⚠️ Concretely: do **not** attach this APK to a GitHub Release. `Incog-Framework/incog-core` is a
  > **public** repo, so a release asset is a public download of the live backend credentials. Share
  > it as a private file (see below) instead.
- A real public release needs **per-device key provisioning** so no shared secret ships in the
  binary.
- Consider a proper distribution channel (Firebase App Distribution / Play closed testing) with a
  policy justification for the sensitive permissions.
