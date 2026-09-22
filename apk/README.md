# Flutter-/Android-Client

Android-Paketname: `com.hbcclient.plsreload`.

Auf einem Debian-System mit Java 17:

```bash
chmod +x setup-and-compile.sh
./setup-and-compile.sh
```

Das Skript installiert Flutter und dessen Linux-Buildabhängigkeiten, erzeugt das
Android-Gerüst, analysiert und testet das Projekt und baut anschließend
`build/app/outputs/flutter-apk/app-release.apk`.

## Passkey-Vertrag

Die App nutzt Android Credential Manager. Dafür muss `api.plsreload.de` die
Digital-Asset-Links für das endgültige Signing-Zertifikat bereitstellen. Der
Server muss WebAuthn-JSON an folgenden Endpunkten liefern/verifizieren:

* `POST /api/authenticate/options`
* `POST /api/authenticate/verify`
* `POST /api/register/options`
* `POST /api/register/verify`

Challenge und User-ID müssen serverseitig geprüft, Challenges einmalig gemacht
und Signaturzähler gespeichert werden. Die App speichert weder private Schlüssel
noch biometrische Daten; dies übernimmt ausschließlich Credential Manager.
