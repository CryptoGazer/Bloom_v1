# bezna для Android

Телефонная страница `web/m` в приложении: один экран с WebView. Файлы страницы лежат в APK (папка `web/` репозитория как есть), запросы `/api/*` идут на `https://bezna.xyz`. Дизайн: `docs/superpowers/specs/2026-11-15-android-app-design.md`.

Что приложение даёт сверх браузера (режим навигатора): экран не гаснет, компас, когда человек стоит, GPS по разрешению приложения, запасной голос системным движком Android.

Голос навигатора на румынском и английском — ElevenLabs: страница берёт запись фразы с сервера (`/api/speak`) и проигрывает её сама. Системный движок Android говорит, когда для выбранного языка не настроен голос, сервер не ответил за 2,5 секунды или ответил ошибкой. Подробности: `docs/voice.md`.

Область покрытия приходит с API: по умолчанию сервер использует `data/out/city-northwest/`
(9,61 км², включая Circumvalațiunii–Dacia и Mircea cel Bătrân). Геометрия и поиск
не зашиты в APK. Для новой сборки приложения `web/m` допускает загрузку всей сети
до 20 000 сегментов одним запросом; в старых APK с лимитом 8 000 большая область
загружается по видимому окну карты при приближении.

Интерфейс и озвучка доступны только на RO/EN. Старые ссылки `?lang=ru` и сохранённый русский язык переключаются на доступный язык (по умолчанию RO). Общий проигрыватель — `web/voice.js`, он включается в APK вместе с мобильной страницей.

## Сборка

Нужны JDK 17 и Android SDK (platform 34, build-tools 34.0.0); `JAVA_HOME` и `ANDROID_HOME` указывают на них.

    cd android
    ./gradlew assembleDebug          # Windows: gradlew.bat assembleDebug
    adb install -r app/build/outputs/apk/debug/app-debug.apk

На macOS установите Android Studio с Android SDK 34 и Build Tools 34.0.0. Пример для установленного JDK 17:

```bash
export JAVA_HOME=$(/usr/libexec/java_home -v 17)
export ANDROID_HOME="$HOME/Library/Android/sdk"
cd android
./gradlew assembleDebug
"$ANDROID_HOME/platform-tools/adb" install -r app/build/outputs/apk/debug/app-debug.apk
```

На Windows в терминале Android Studio: `cd android`, затем `gradlew.bat assembleDebug`. Не переносите чужой `local.properties`: он содержит локальный путь SDK и исключён из Git. В репозитории нет абсолютных путей Windows/macOS.

Сборка проверена на macOS с JDK 21, Gradle 8.7, SDK 34. Тестовый SDK этого запуска находится в `/tmp/bezna-android-sdk` (временный, не замена постоянной установке). APK — `android/app/build/outputs/apk/debug/app-debug.apk`. Если установленная сборка Тимура подписана другим debug-ключом, Android отклонит `install -r`: используйте тот же ключ либо удалите прежнюю тестовую сборку, учитывая потерю её локальных настроек.

Файлы страницы попадают в APK при сборке: после любой правки в `web/` приложение нужно собрать и поставить заново, иначе в нём останется старая страница.

Другой сервер: `./gradlew assembleDebug -PbaseUrl=https://example.org` (нужен HTTPS: без него WebView не даёт геолокацию и микрофон).

Страница ↔ приложение: `window.BeznaNative.nav(on)`, `.speak(text, lang)`, `.stopSpeaking()`; приложение вызывает `window.bzCompass(deg)`. Код моста — `app/src/main/java/xyz/bezna/app/MainActivity.java`, сторона страницы — `web/m/m.js`.

## Дальше

Ведение с выключенным экраном (сервис и логика `web/m/nav.js` на Kotlin), подсказка в уведомлении, пересчёт при уходе с маршрута, офлайн-карта района, публикация в Google Play.
