# Installing the Haman cough monitor (Android)

**File:** [`HamanCough-v0.2.0.apk`](HamanCough-v0.2.0.apk) ·  42M · Android 8.0 or newer

## Install

1. On the phone, open this link in the browser. It downloads the APK directly:
   **https://github.com/rezaraf20/HamanHealth/raw/CoughAnalysisModule/HamanCough-v0.2.0.apk**
2. Tap the downloaded file. If Android blocks it, allow **Install unknown apps** for
   your browser when prompted (Settings → Apps → *your browser* → Install unknown apps).
3. Tap **Install**, then **Open**.

If Android refuses because the app is already installed from a different build,
uninstall the old **Haman** app first. Samsung and some other phones may show a Play
Protect warning for apps installed outside the Play Store — choose **Install anyway**.

## First launch

1. Allow **microphone** and **notifications**.
2. Tap **Allow background running** on the Tonight screen. Without it, Android usually
   stops the recording partway through the night.
3. **Settings → Run microphone diagnostics** — cough 2–3 times when each route starts
   (~25 s). Which microphone route hears coughs best differs between phone models; this
   picks the right one for your phone. Do it once per phone.
4. On **Huawei**: also Settings → Battery → App launch → **Haman** → Manage manually, and
   enable all three switches. EMUI otherwise closes the app overnight.

Then place the phone on the nightstand (plugged in) and tap **Start monitoring**.
Detected coughs, sneezes and snoring appear under **History**, where each event can be
played back and marked "Me / Someone else / Not a real event".

## Notes

- All audio is analysed on the phone. Nothing is uploaded.
- This logs sleep sounds. It is **not** a medical device and does not diagnose anything.
- Integrity check — SHA-256 of the APK:
  `2116012a4dde08857742d447f32e6ed5336113c942ed3fdbafe017ce0245da2b`

Source and documentation: [`CoughAnalysisModule/`](CoughAnalysisModule/README.md).
