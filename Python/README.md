# Python-Client

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python musik_client.py
```

Der Client nutzt Qt/PySide6 und benötigt deshalb keine separate Tcl/Tk-
Installation. Das gilt insbesondere für portable oder unvollständige
Python-Installationen unter Windows, bei denen `init.tcl` fehlt.

Der Client übernimmt Player, Playlists, Server-Playlists, Webchat, Einstellungen
und die beiden Anmeldewege. Für Passkeys öffnet er die WebAuthn-Seite des Servers;
dadurch bleiben privater Schlüssel und Biometrie im Credential Manager des
Betriebssystems. Der Browser-Flow verwendet `/register` und `/get`; die native
API verwendet `/api/register/options`, `/api/register/verify`,
`/api/authenticate/options` und `/api/authenticate/verify`. Session-Cookies
bleiben zwischen Options- und Verify-Request erhalten. Zugangsdaten und Token
werden nur im Arbeitsspeicher gehalten. Die Konfigurationsdatei enthält kein Secret.

Windows-Ersatzimplementierungen und die unvermeidbaren Grenzen gegenüber der
Android-/Tasker-Laufzeit sind in
[`TASKER_WINDOWS_COMPATIBILITY.md`](TASKER_WINDOWS_COMPATIBILITY.md) vollständig
aufgeführt.
