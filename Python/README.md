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
Betriebssystems. Erwartet werden die Endpunkte unter `/passkeys/authenticate` und
`/passkeys/register`. Das vom Authentifizierungs-Flow gelieferte kurzlebige Token
wird nur im Arbeitsspeicher gehalten. Die Konfigurationsdatei enthält kein Secret.
