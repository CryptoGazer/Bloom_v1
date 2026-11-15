# bezna для Android

Телефонная страница `web/m` в приложении: один экран с WebView. Файлы страницы лежат в APK (папка `web/` репозитория как есть), запросы `/api/*` идут на `https://bezna.xyz`. Дизайн: `docs/superpowers/specs/2026-11-15-android-app-design.md`.

Что приложение даёт сверх браузера (режим навигатора): голос системным движком Android, экран не гаснет, компас, когда человек стоит, GPS по разрешению приложения.

## Сборка

Нужны JDK 17 и Android SDK (platform 34, build-tools 34.0.0); `JAVA_HOME` и `ANDROID_HOME` указывают на них.

    cd android
    ./gradlew assembleDebug
    adb install -r app/build/outputs/apk/debug/app-debug.apk

Другой сервер: `./gradlew assembleDebug -PbaseUrl=https://example.org` (нужен HTTPS: без него WebView не даёт геолокацию и микрофон).

Страница ↔ приложение: `window.BeznaNative.nav(on)`, `.speak(text, lang)`, `.stopSpeaking()`; приложение вызывает `window.bzCompass(deg)`. Код моста — `app/src/main/java/xyz/bezna/app/MainActivity.java`, сторона страницы — `web/m/m.js`.

## Дальше

Ведение с выключенным экраном (сервис и логика `web/m/nav.js` на Kotlin), подсказка в уведомлении, пересчёт при уходе с маршрута, офлайн-карта района, публикация в Google Play.
