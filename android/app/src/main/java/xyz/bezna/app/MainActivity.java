package xyz.bezna.app;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.SystemClock;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.view.WindowManager;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
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

/**
 * bezna: the phone page (web/m) in a WebView. The page's files come from the APK, the API from BASE_URL.
 * For the navigator the page gets window.BeznaNative (class Bridge): the system voice, a screen that stays on
 * and the phone's compass, which a browser page does not have.
 */
public class MainActivity extends Activity implements SensorEventListener {
    private static final Uri BASE = Uri.parse(BuildConfig.BASE_URL);
    private static final int ASK_LOCATION = 1, ASK_MIC = 2;
    private static final String TAG = "bezna", GOOGLE_TTS = "com.google.android.tts";
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
    private TextToSpeech tts;
    private boolean ttsReady, navOn;
    private SensorManager sensors;
    private long compassAt;

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
        // Google's engine supports Romanian and English; some phones' own engines list every language but speak only
        // English (vivo's com.vivo.aiservice). Google's if it is installed, the phone's default otherwise.
        final String engine = installed(GOOGLE_TTS) ? GOOGLE_TTS : null;
        tts = new TextToSpeech(this, status -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            if (!ttsReady) return;
            Log.i(TAG, "speech engine " + engine + " (null: the default " + tts.getDefaultEngine() + ")");
        }, engine);
        sensors = (SensorManager) getSystemService(SENSOR_SERVICE);
        web.addJavascriptInterface(new Bridge(), "BeznaNative");
        if (state == null) web.loadUrl(BASE + "/m/"); else web.restoreState(state);
    }

    @Override protected void onSaveInstanceState(Bundle out) { super.onSaveInstanceState(out); web.saveState(out); }
    @Override protected void onResume() { super.onResume(); web.onResume(); compass(navOn); }
    @Override protected void onPause() { compass(false); web.onPause(); super.onPause(); }
    @Override protected void onDestroy() { if (tts != null) tts.shutdown(); super.onDestroy(); }

    /** "Back" walks the page's screens, as in a browser; on the first screen it leaves the app. */
    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack(); else super.onBackPressed();
    }

    private boolean installed(String app) {
        try { getPackageManager().getPackageInfo(app, 0); return true; } catch (PackageManager.NameNotFoundException none) { return false; }
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

    // ---------- the navigator ----------

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

    /** The phone's direction, degrees clockwise from north, to the page at most four times a second. */
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
                if (!ttsReady) { Log.w(TAG, "speak: no speech engine"); return; }
                Locale locale = Locale.forLanguageTag(lang);
                if (!locale.getLanguage().equals("en") && !locale.getLanguage().equals("ro")) return;
                int language = tts.setLanguage(locale);
                if (language < TextToSpeech.LANG_AVAILABLE) {
                    Log.w(TAG, "speak: missing voice data for " + lang);
                    return; // Do not read Romanian using the previously selected English voice.
                }
                int queued = tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "bezna");
                Log.i(TAG, "speak " + lang + ": language " + language + ", queued " + queued + ", voice " + tts.getVoice());
            });
        }

        @JavascriptInterface
        public void stopSpeaking() { runOnUiThread(() -> { if (ttsReady) tts.stop(); }); }
    }

    // ---------- the page ----------

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
