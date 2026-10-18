# Installing Haman Health (Android)

**File:** [`HamanCough-v0.3.1.apk`](HamanCough-v0.3.1.apk) · Android 8.0 or newer

## Install

1. On the phone, open this link in the browser. It downloads the APK directly:
   **https://github.com/rezaraf20/HamanHealth/raw/android-app/HamanCough-v0.3.1.apk**
2. Tap the downloaded file. If Android blocks it, allow **Install unknown apps** for
   your browser when prompted (Settings → Apps → *your browser* → Install unknown apps).
3. Tap **Install**, then **Open**.

Version 0.3.1 installs over 0.3.0 and 0.2.0 and keeps the nights already recorded on the phone;
they are uploaded once you sign in. Samsung and some other phones may show a Play
Protect warning for apps installed outside the Play Store — choose **Install anyway**.

## First launch

1. The app opens the Haman Health sign-in screen. Sign in, or create an account. The app
   needs an internet connection to open; a running night keeps recording without one.
2. **Night session → Start**: allow **microphone** and **notifications**, then
   **Allow** background running when asked. Without it, Android usually stops the
   recording partway through the night.
3. Once per phone: long-press the app icon → **Microphone test**, and cough 2–3 times
   when each route starts (~25 s). Which microphone route hears coughs best differs
   between phone models; this picks the right one for your phone.
4. On **Huawei**: also Settings → Battery → App launch → **Haman Health** → Manage
   manually, and enable all three switches. EMUI otherwise closes the app overnight.

Place the phone on the nightstand (plugged in) and start the night. A running night can
always be stopped from its notification, even without a connection.

## Notes

- Sounds are analysed on the phone. After sign-in the app uploads the detected events
  (time, type, scores), and a 2.5-second clip of each cough and sneeze unless you switch
  **Short audio clips** off under Account → Privacy. A whole night is never recorded or
  uploaded. Uploads wait for a connection and resume by themselves.
- This logs sleep sounds. It is **not** a medical device and does not diagnose anything.
- Integrity check — SHA-256 of the APK:
  `62d4f996691729207063ae432bf7a784b8ba19a2131568ce24d196dbbfa25fb8`

Source and documentation: [`CoughAnalysisModule/`](CoughAnalysisModule/README.md),
[`backend/docs/ANDROID_APP_TASK.md`](backend/docs/ANDROID_APP_TASK.md).
