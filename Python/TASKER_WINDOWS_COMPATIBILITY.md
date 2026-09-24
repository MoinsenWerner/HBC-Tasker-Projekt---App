# Windows-Ersatzimplementierungen und Grenzen

Die Python-Anwendung ersetzt Android-Intents durch Windows-Shell-Aufrufe:
HTTP(S), `mailto:` und `spotify:` werden mit der registrierten Standardanwendung
geöffnet; Dateien und weitere URI-Schemas werden unter Windows über
`os.startfile` an die passende Dateizuordnung übergeben.

Weitere Ersetzungen:

* Tasker-Verzeichnisse werden nach `%LOCALAPPDATA%\HBC Musik Client` umgeleitet.
* Flash-/Dialog-Aktionen werden als Qt-Dialog dargestellt.
* Benachrichtigungen werden über Windows Toast Notifications ausgegeben.
* HTTP-, Datei-, Variablen-, Ersetzen-, Aufteilen-, Warte-, Browser-, Szenen-
  und Untertask-Aktionen werden durch den Python-Tasker-Interpreter ausgeführt.
* Zeitprofile werden in der laufenden Anwendung statt vom Android-System geplant.

## Nicht identisch umsetzbare Tasker-Funktionen

Folgende Funktionen benötigen Android, Tasker oder ein nicht im Export
enthaltenes Plug-in und müssen unter Windows entfallen beziehungsweise werden
auf eine einfache Windows-Benachrichtigung reduziert:

1. AutoNotification-spezifische Notification-IDs, Button-Commands, MediaStyle,
   persistente Gruppen und das Abbrechen fremder Android-Benachrichtigungen.
2. Samsung-spezifische Notification-Channels und deren Systemeinstellungen.
3. Android-Power-Menu-Kacheln und Tasker-Secondary-App-Aktivitäten.
4. Das Aktivieren, Deaktivieren oder Stoppen von Tasker-Profilen und parallel
   laufenden Tasker-Tasks; Python verwendet stattdessen seinen eigenen Zustand.
5. Android-Activity-/Broadcast-/Service-Intents ohne öffentliches URI- oder
   Dateischema. Öffentliche Links und Dateien werden durch Windows Shell ersetzt.
6. Stille APK-Installation, Paketmanagerabfragen und Starten installierter
   Android-Packages. APK-Dateien können unter Windows nur heruntergeladen werden.
7. Android-Fused-Location und Taskers `%gl_latitude`/`%gl_longitude`. Eine
   Windows-Positionsfreigabe benötigt eine separat registrierte WinRT-App und ist
   in der portablen Python-Datei nicht zuverlässig verfügbar.
8. Tasker-Overlay-Szenen mit exakten Android-Pixelkoordinaten, Z-Order und
   Statusleistenverhalten. Die Inhalte werden als native skalierbare Qt-Widgets
   dargestellt.
9. Tasker-JavaScript mit `global()`/`setGlobal()` und direktem Zugriff auf die
   Tasker-Laufzeit. Variablenoperationen werden nativ ausgeführt, eingebettete
   Skripte mit Tasker-APIs jedoch nicht evaluiert.
10. Plug-in-Konfigurationsaktionen, deren Implementierung nur als serialisiertes
    Android-Bundle im Export vorliegt und deren Plug-in nicht mitgeliefert wurde.

Die Spotify-/HBC-Serveraktionen, Navigation, Dateiablage, Browseraufrufe,
Windows-Benachrichtigungen, Dialoge und URI-/Datei-Intents besitzen native
Windows-Ersatzimplementierungen.
