# Android App (bezna) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An Android app that is the phone web version (`web/m`) one to one, with a navigator that gets what a browser page lacks: voice, a screen that stays on, a compass, GPS through an app permission.

**Architecture:** A thin shell in `android/`: one Activity with a WebView that opens `https://bezna.xyz/m/`. GET requests to that host, except `/api/*`, are answered from the APK's assets (the repository's `web/` folder as it is); the API goes to the network, so page and API share one origin and the backend is untouched. The page talks to the shell through `window.BeznaNative`; the shell calls `window.bzCompass(deg)`.

**Tech Stack:** Java 17, Android Gradle Plugin 8.5.2, Gradle 8.7, compileSdk/targetSdk 34, minSdk 26, no third-party libraries. Web side: `web/m/m.js` (vanilla JS).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-15-android-app-design.md`. Code stop 13:00, 15.11.2026.
- The interface has one source: `web/`. No copies of web files in `android/` (the launcher icon is the only exception: Android needs it as a resource).
- In a plain browser the page behaves as before: every hook checks `window.BeznaNative`.
- No new visible labels or buttons in the UI.
- Toolchain lives outside the repository in `C:\Users\Timur\android-dev` (`jdk/`, `sdk/`, `gradle-8.7/`). The APK is not committed.
- Shell for every build command (Git Bash):
  `export JAVA_HOME="$(ls -d /c/Users/Timur/android-dev/jdk/jdk-17*)" ANDROID_HOME="C:/Users/Timur/android-dev/sdk" PATH="$JAVA_HOME/bin:/c/Users/Timur/android-dev/sdk/platform-tools:$PATH"`

## The navigator: what is in this plan and what comes after

The navigator is the reason for an app at all. Today (Tasks 1–2): GPS by app permission, screen kept on, system voice, compass when standing, a demo walk by a long press on «Pornește».

After the hackathon, a separate plan (not part of this one): guidance with the screen off (a foreground service, `nav.js` logic in Kotlin), the next manoeuvre in the notification and on the lock screen, audio focus, automatic re-routing off the route, an offline map of the district, signing and Google Play.

---

### Task 1: The shell: the page from the APK, the API from the network

**Files:**
- Create: `android/settings.gradle`, `android/build.gradle`, `android/gradle.properties`, `android/.gitignore`
- Create: `android/app/build.gradle`, `android/app/src/main/AndroidManifest.xml`
- Create: `android/app/src/main/java/xyz/bezna/app/MainActivity.java`
- Create: `android/app/src/main/res/values/styles.xml`, `android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png` (copy of `web/favicon.png`)
- Generated and committed: `android/gradlew`, `android/gradlew.bat`, `android/gradle/wrapper/*`

**Interfaces:**
- Produces: `MainActivity` with fields `web` (WebView), and the place where Task 2 adds `web.addJavascriptInterface(new Bridge(), "BeznaNative")`.

- [ ] **Step 1: Gradle files**

`android/settings.gradle`:

```groovy
pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }
dependencyResolutionManagement { repositories { google(); mavenCentral() } }
rootProject.name = 'bezna'
include ':app'
```

`android/build.gradle`:

```groovy
plugins { id 'com.android.application' version '8.5.2' apply false }
```

`android/gradle.properties`:

```properties
org.gradle.jvmargs=-Xmx2g
android.useAndroidX=true
```

`android/.gitignore`:

```
.gradle/
build/
local.properties
```

`android/app/build.gradle`:

```groovy
plugins { id 'com.android.application' }

android {
    namespace 'xyz.bezna.app'
    compileSdk 34
    defaultConfig {
        applicationId 'xyz.bezna.app'
        minSdk 26
        targetSdk 34
        versionCode 1
        versionName '1.0'
        // the server the page and the API belong to; the page itself comes from the APK
        buildConfigField 'String', 'BASE_URL', "\"${project.findProperty('baseUrl') ?: 'https://bezna.xyz'}\""
    }
    buildFeatures { buildConfig true }
    // the interface has one source: the repository's web/ folder, as it is
    sourceSets { main { assets.srcDirs = ['../../web'] } }
    compileOptions {
        sourceCompatibility JavaVersion.VERSION_17
        targetCompatibility JavaVersion.VERSION_17
    }
    lint { abortOnError false }
}
```

- [ ] **Step 2: Manifest, theme, icon**

`android/app/src/main/AndroidManifest.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
    <uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
    <uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
    <!-- the system voice (TextToSpeech) is another app: Android 11+ must be told we look for it -->
    <queries><intent><action android:name="android.intent.action.TTS_SERVICE" /></intent></queries>

    <application android:label="bezna" android:icon="@mipmap/ic_launcher" android:theme="@style/Bezna" android:allowBackup="false">
        <activity android:name=".MainActivity" android:exported="true" android:screenOrientation="portrait"
            android:configChanges="orientation|screenSize|keyboardHidden|uiMode" android:windowSoftInputMode="adjustResize">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
```

`android/app/src/main/res/values/styles.xml`:

```xml
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <style name="Bezna" parent="@android:style/Theme.Material.NoActionBar">
        <item name="android:windowBackground">@android:color/black</item>
        <item name="android:statusBarColor">#0B0B0B</item>
        <item name="android:navigationBarColor">#171717</item>
    </style>
</resources>
```

Icon: `mkdir -p android/app/src/main/res/mipmap-xxxhdpi && cp web/favicon.png android/app/src/main/res/mipmap-xxxhdpi/ic_launcher.png`

- [ ] **Step 3: `MainActivity.java`**

```java
package xyz.bezna.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.GeolocationPermissions;
import android.webkit.PermissionRequest;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.IOException;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/** bezna: the phone page (web/m) in a WebView. The page's files come from the APK, the API from BASE_URL. */
public class MainActivity extends Activity {
    private static final Uri BASE = Uri.parse(BuildConfig.BASE_URL);
    private static final int ASK_LOCATION = 1, ASK_MIC = 2;
    private static final Map<String, String> MIME = new HashMap<>();
    static {
        MIME.put("html", "text/html"); MIME.put("js", "text/javascript"); MIME.put("css", "text/css");
        MIME.put("json", "application/json"); MIME.put("png", "image/png"); MIME.put("ico", "image/x-icon");
        MIME.put("svg", "image/svg+xml"); MIME.put("woff2", "font/woff2");
    }

    private WebView web;
    private String geoOrigin;
    private GeolocationPermissions.Callback geoCallback;
    private PermissionRequest micRequest;

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        WebView.setWebContentsDebuggingEnabled(BuildConfig.DEBUG);
        web = new WebView(this);
        web.setBackgroundColor(0xFF0B0B0B);
        setContentView(web);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setGeolocationEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        if (state == null) web.loadUrl(BASE + "/m/"); else web.restoreState(state);
    }

    @Override protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }
    @Override protected void onResume() { super.onResume(); web.onResume(); }
    @Override protected void onPause() { web.onPause(); super.onPause(); }

    /** "Back" walks the page's screens, as in a browser; on the first screen it leaves the app. */
    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    private boolean granted(String permission) {
        return checkSelfPermission(permission) == PackageManager.PERMISSION_GRANTED;
    }

    @Override
    public void onRequestPermissionsResult(int code, String[] permissions, int[] results) {
        boolean ok = false;
        for (int r : results) ok |= r == PackageManager.PERMISSION_GRANTED;
        if (code == ASK_LOCATION && geoCallback != null) {
            geoCallback.invoke(geoOrigin, ok, false);
            geoCallback = null;
        }
        if (code == ASK_MIC && micRequest != null) {
            if (ok) micRequest.grant(new String[] {PermissionRequest.RESOURCE_AUDIO_CAPTURE}); else micRequest.deny();
            micRequest = null;
        }
    }

    private class Client extends WebViewClient {
        /** Files of the page from the APK (the web/ folder); the API and everything else from the network. */
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            Uri u = request.getUrl();
            String path = u.getPath();
            if (!"GET".equals(request.getMethod()) || !BASE.getHost().equals(u.getHost()) || path == null || path.startsWith("/api/")) return null;
            String file = (path.endsWith("/") ? path + "index.html" : path).substring(1);
            String ext = file.substring(file.lastIndexOf('.') + 1).toLowerCase(Locale.ROOT);
            String mime = MIME.get(ext);
            if (mime == null) return null;
            try {
                boolean text = mime.startsWith("text/") || ext.equals("json") || ext.equals("svg");
                WebResourceResponse r = new WebResourceResponse(mime, text ? "utf-8" : null, getAssets().open(file));
                Map<String, String> headers = new HashMap<>();
                headers.put("Cache-Control", "no-cache");
                r.setResponseHeaders(headers);
                return r;
            } catch (IOException notInApk) {
                return null;
            }
        }

        /** Other sites (map attribution, sources) open in the browser. */
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            if (BASE.getHost().equals(request.getUrl().getHost())) return false;
            try { startActivity(new Intent(Intent.ACTION_VIEW, request.getUrl())); } catch (Exception noBrowser) { /* nothing to open it with */ }
            return true;
        }
    }

    private class Chrome extends WebChromeClient {
        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback callback) {
            if (granted(Manifest.permission.ACCESS_FINE_LOCATION)) { callback.invoke(origin, true, false); return; }
            geoOrigin = origin;
            geoCallback = callback;
            requestPermissions(new String[] {Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION}, ASK_LOCATION);
        }

        @Override
        public void onPermissionRequest(PermissionRequest request) {
            boolean audio = false;
            for (String r : request.getResources()) audio |= PermissionRequest.RESOURCE_AUDIO_CAPTURE.equals(r);
            if (!audio) { request.deny(); return; }
            if (granted(Manifest.permission.RECORD_AUDIO)) { request.grant(new String[] {PermissionRequest.RESOURCE_AUDIO_CAPTURE}); return; }
            micRequest = request;
            requestPermissions(new String[] {Manifest.permission.RECORD_AUDIO}, ASK_MIC);
        }
    }
}
```

- [ ] **Step 4: Wrapper and build**

Run in `android/` (with the exports from Global Constraints): `/c/Users/Timur/android-dev/gradle-8.7/bin/gradle wrapper --gradle-version 8.7 && ./gradlew assembleDebug`
Expected: `BUILD SUCCESSFUL`, the file `android/app/build/outputs/apk/debug/app-debug.apk`.

Check the assets are inside: `unzip -l app/build/outputs/apk/debug/app-debug.apk | grep -E "assets/m/(index.html|m.js|nav.js)|assets/vendor/leaflet/leaflet.js|assets/ask.js"` — five lines.

- [ ] **Step 5: On the phone** (USB debugging on): `adb devices` shows the phone; `adb install -r app/build/outputs/apk/debug/app-debug.apk`; `adb shell am start -n xyz.bezna.app/.MainActivity`. Expected: the start screen of `/m/` with the map; a route A → B is calculated; «Aici sunt» asks for the location permission once; Back from the results returns to the start screen.

- [ ] **Step 6: Commit** — `git add android && git commit -m "feat: Android shell: the phone page in a WebView, its files from the APK"`

### Task 2: The navigator bridge

**Files:**
- Modify: `web/m/m.js` (voice, `BeznaNative.nav`, `window.bzCompass`, long press on «Pornește»)
- Modify: `android/app/src/main/java/xyz/bezna/app/MainActivity.java` (class `Bridge`, TextToSpeech, rotation sensor, keep the screen on)

**Interfaces:**
- Consumes: `MainActivity.web`.
- Produces: `window.BeznaNative.nav(on: boolean)`, `.speak(text: string, lang: string)` with `lang` a BCP-47 tag (`ro-RO`, `en-GB`, `ru-RU`), `.stopSpeaking()`; the shell calls `window.bzCompass(deg: number)`, degrees clockwise from north, at most four times a second while the navigator is open.

- [ ] **Step 1: `web/m/m.js`, the hooks**

Next to the other state (after `let calcReq = -1;`):

```js
// the Android app (android/) puts BeznaNative into the page: voice, a screen that stays on, a compass
const native = () => window.BeznaNative || null;
const canSpeak = () => !!(native() || window.speechSynthesis);
function speak(text) {
  const lang = { ro: 'ro-RO', en: 'en-GB', ru: 'ru-RU' }[LANG] || 'ro-RO';
  if (native()) { native().speak(text, lang); return; }
  if (!window.speechSynthesis) return;
  const u = new SpeechSynthesisUtterance(text);
  u.lang = lang;
  speechSynthesis.speak(u);
}
function hush() { if (native()) native().stopSpeaking(); else if (window.speechSynthesis) speechSynthesis.cancel(); }
```

`startNav`: signature `function startNav(demo = false)`; `const sim = demo || /[?&]sim=1/.test(location.search);`; after `go('nav');` add `if (native()) native().nav(true);`.

`stopNav`: replace `if (window.speechSynthesis) speechSynthesis.cancel();` with `hush(); if (native()) native().nav(false);`.

`updateNav`, the voice block becomes:

```js
  if (nav.voice && canSpeak() && left < 60 && nav.spoken !== nextI) {
    nav.spoken = nextI;
    speak(`${round(left)}. ${say(man)}`);
  }
```

`onPos`: where a heading is known for this fix (`if (heading != null && !isNaN(heading)) nav.heading = heading;`) also set `nav.headingAt = Date.now();`.

After `onPos`:

```js
// the phone's compass (from the app): the direction while standing, when the GPS has none
window.bzCompass = deg => {
  if (!nav || nav.sim || !myPos || Date.now() - (nav.headingAt || 0) < 3000) return;
  nav.heading = deg;
  showMe(myPos.lat, myPos.lng, deg);
};
```

`ACT.start` and the long press (in the app only: a demo walk along the route, as `?sim=1`):

```js
ACT.start = () => { if (!nav) startNav(); };
let holdT = null;
$('screen').addEventListener('pointerdown', e => {
  if (!native() || !e.target.closest('[data-act="start"]')) return;
  clearTimeout(holdT);
  holdT = setTimeout(() => { if (!nav) startNav(true); }, 700);
});
for (const ev of ['pointerup', 'pointercancel', 'pointerleave']) $('screen').addEventListener(ev, () => clearTimeout(holdT));
$('screen').addEventListener('contextmenu', e => { if (native() && e.target.closest('[data-act="start"]')) e.preventDefault(); });
```

- [ ] **Step 2: Check the hooks in a desktop browser** (`http://localhost:8001/m/`, a new tab). In the console: `window.BeznaNative = { log: [], nav(on) { this.log.push('nav:' + on); }, speak(t, l) { this.log.push('speak:' + l + ':' + t); }, stopSpeaking() { this.log.push('stop'); } }`, set two points, `startNav(true)`, press the voice button, wait for a manoeuvre, `ACT.navStop` (or Back). Expected in `BeznaNative.log`: `nav:true`, a `speak:ro-RO:…` line, `stop`, `nav:false`. Without `BeznaNative` (reload) the navigator works as before. `node --check web/m/m.js`, `node --test web/m/nav.test.cjs` → 10 pass.

- [ ] **Step 3: `MainActivity.java`, the bridge**

New imports: `android.hardware.Sensor`, `android.hardware.SensorEvent`, `android.hardware.SensorEventListener`, `android.hardware.SensorManager`, `android.os.SystemClock`, `android.speech.tts.TextToSpeech`, `android.view.WindowManager`, `android.webkit.JavascriptInterface`.

Class header: `public class MainActivity extends Activity implements SensorEventListener`.

Fields:

```java
    private TextToSpeech tts;
    private boolean ttsReady, navOn;
    private SensorManager sensors;
    private long compassAt;
```

In `onCreate`, before `loadUrl`:

```java
        tts = new TextToSpeech(this, status -> ttsReady = status == TextToSpeech.SUCCESS);
        sensors = (SensorManager) getSystemService(SENSOR_SERVICE);
        web.addJavascriptInterface(new Bridge(), "BeznaNative");
```

Lifecycle and the navigator state:

```java
    @Override protected void onResume() { super.onResume(); web.onResume(); compass(navOn); }
    @Override protected void onPause() { compass(false); web.onPause(); super.onPause(); }
    @Override protected void onDestroy() { if (tts != null) tts.shutdown(); super.onDestroy(); }

    /** The navigator is open: the screen stays on and the compass reports the phone's direction. */
    private void setNav(boolean on) {
        navOn = on;
        if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        compass(on);
        if (!on && ttsReady) tts.stop();
    }

    private void compass(boolean on) {
        sensors.unregisterListener(this);
        Sensor rotation = sensors.getDefaultSensor(Sensor.TYPE_ROTATION_VECTOR);
        if (on && rotation != null) sensors.registerListener(this, rotation, SensorManager.SENSOR_DELAY_UI);
    }

    @Override
    public void onSensorChanged(SensorEvent event) {
        long now = SystemClock.elapsedRealtime();
        if (now - compassAt < 250) return;
        compassAt = now;
        float[] matrix = new float[9], orientation = new float[3];
        SensorManager.getRotationMatrixFromVector(matrix, event.values);
        SensorManager.getOrientation(matrix, orientation);
        long deg = Math.round((Math.toDegrees(orientation[0]) + 360) % 360);
        web.evaluateJavascript("window.bzCompass&&window.bzCompass(" + deg + ")", null);
    }

    @Override public void onAccuracyChanged(Sensor sensor, int accuracy) { }

    /** window.BeznaNative in the page (web/m/m.js). Called on a WebView thread, so everything hops to the UI thread. */
    private class Bridge {
        @JavascriptInterface
        public void nav(final boolean on) { runOnUiThread(() -> setNav(on)); }

        @JavascriptInterface
        public void speak(final String text, final String lang) {
            runOnUiThread(() -> {
                if (!ttsReady) return;
                tts.setLanguage(Locale.forLanguageTag(lang));
                tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "bezna");
            });
        }

        @JavascriptInterface
        public void stopSpeaking() { runOnUiThread(() -> { if (ttsReady) tts.stop(); }); }
    }
```

(The two one-line `onResume` / `onPause` of Task 1 are replaced by the ones above.)

- [ ] **Step 4: Build and install** — `./gradlew assembleDebug && adb install -r app/build/outputs/apk/debug/app-debug.apk`. Expected: `BUILD SUCCESSFUL`, `Success`.

- [ ] **Step 5: On the phone.** A route, a long press on «Pornește»: the demo walk starts, the screen does not dim for a minute, the voice button on: a phrase is spoken before a turn. A short press on «Pornește»: real GPS (permission asked once), standing still the direction cone follows the phone as it turns. Back leaves the navigator, the voice stops. `adb logcat -d | grep -i "chromium.*console"` shows no errors of the page.

- [ ] **Step 6: Commit** — `git add web/m/m.js android && git commit -m "feat: the navigator in the app: system voice, the screen stays on, compass, a demo walk by a long press"`

### Task 3: Instructions, the whole check, merge

**Files:**
- Create: `android/README.md`
- Modify: `README.md` (one line that points to `android/`)

- [ ] **Step 1: `android/README.md`**

```markdown
# bezna для Android

Телефонная страница `web/m` в приложении: один экран с WebView. Файлы страницы лежат в APK (папка `web/` репозитория как есть), запросы `/api/*` идут на `https://bezna.xyz`. Дизайн: `docs/superpowers/specs/2026-11-15-android-app-design.md`.

Что приложение даёт сверх браузера (режим навигатора): голос системным движком Android, экран не гаснет, компас, когда человек стоит, GPS по разрешению приложения. Долгое нажатие на «Pornește» — демонстрационная прогулка по маршруту.

## Сборка

Нужны JDK 17 и Android SDK (platform 34, build-tools 34.0.0); `JAVA_HOME` и `ANDROID_HOME` указывают на них.

    cd android
    ./gradlew assembleDebug
    adb install -r app/build/outputs/apk/debug/app-debug.apk

Другой сервер: `./gradlew assembleDebug -PbaseUrl=https://example.org` (нужен HTTPS: без него WebView не даёт геолокацию и микрофон).

Страница ↔ приложение: `window.BeznaNative.nav(on)`, `.speak(text, lang)`, `.stopSpeaking()`; приложение вызывает `window.bzCompass(deg)`. Код моста — `MainActivity.java`, сторона страницы — `web/m/m.js`.

## Дальше

Ведение с выключенным экраном (сервис и логика `web/m/nav.js` на Kotlin), подсказка в уведомлении, пересчёт при уходе с маршрута, офлайн-карта района, публикация в Google Play.
```

- [ ] **Step 2: The whole check.** `../.venv/Scripts/python -m pytest backend/tests -q -p no:warnings` → all pass; `node --test web/m/nav.test.cjs` → 10 pass. On the phone: start, a route A → B, a loop, a request in plain words by text, the navigator (demo and real GPS), voice, Back, a language switch.

- [ ] **Step 3: Commit, merge, push** — `git add android/README.md README.md && git commit -m "docs: how to build the Android app"`; `git checkout main && git merge --ff-only feat/android-app && git push origin main`.
