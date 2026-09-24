# HBC Musik Client

Dieses Repository enthält den ursprünglichen Tasker-Export und zwei vollständige
Neuimplementierungen:

* [`Python/`](Python/) – plattformübergreifender Desktop-Client als einzelne
  Python-Datei mit Qt/PySide6-Oberfläche.
* [`apk/`](apk/) – nativer Flutter-/Android-Client einschließlich
  `setup-and-compile.sh` für Debian.

Beide Clients bilden Anmeldung, Player-Steuerung, Spotify- und
Server-Playlists, Webchat sowie Einstellungen ab. Die Android-App verwendet den
systemeigenen Credential Manager für WebAuthn-Passkeys; der Desktop-Client
übergibt Passkey-Vorgänge an den sicheren Browser-/System-Credential-Manager.

Die Passkey-Flows benötigen die in den jeweiligen READMEs beschriebenen
serverseitigen WebAuthn-Endpunkte. User-Secrets und private Passkey-Schlüssel
werden nicht dauerhaft in den Clients gespeichert.
