import 'package:credential_manager/credential_manager.dart';
import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'api.dart';

const rpId = 'api.plsreload.de';
final credentialManager = CredentialManager();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (credentialManager.isSupportedPlatform) {
    await credentialManager.init(preferImmediatelyAvailableCredentials: false);
  }
  runApp(const MusikApp());
}

class MusikApp extends StatelessWidget {
  const MusikApp({super.key});
  @override
  Widget build(BuildContext context) => MaterialApp(
        debugShowCheckedModeBanner: false,
        title: 'HBC Musik Client',
        themeMode: ThemeMode.dark,
        darkTheme: ThemeData(
          brightness: Brightness.dark,
          colorScheme: ColorScheme.fromSeed(seedColor: const Color(0xff1ed760), brightness: Brightness.dark),
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xff101217),
          cardTheme: const CardThemeData(margin: EdgeInsets.symmetric(horizontal: 16, vertical: 8)),
          inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
        ),
        home: const LoginPage(),
      );
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key});
  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> {
  final userController = TextEditingController();
  final secretController = TextEditingController();
  final api = HbcApi();
  bool busy = false;

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((prefs) {
      if (!mounted) return;
      setState(() {
        userController.text = prefs.getString('user_id') ?? '';
        api.baseUrl = prefs.getString('api_url') ?? api.baseUrl;
      });
    });
  }

  Future<void> execute(Future<String> Function() action) async {
    if (userController.text.trim().isEmpty) return showError('Bitte User-ID eingeben.');
    setState(() => busy = true);
    try {
      final token = await action();
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('user_id', userController.text.trim());
      if (!mounted) return;
      api
        ..token = token
        ..userId = userController.text.trim();
      Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => HomePage(api: api, userId: userController.text.trim())));
    } catch (error) {
      showError(error.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<String> passkeyLogin() async {
    final options = await api.passkeyLoginOptions(userController.text.trim());
    final credentials = await credentialManager.getCredentials(
      passKeyOption: CredentialLoginOptions.fromJson(options),
      fetchOptions: FetchOptionsAndroid(passKey: true, passwordCredential: false, googleCredential: false),
    );
    final passkey = credentials.publicKeyCredential;
    if (passkey == null) throw const ApiException('Kein Passkey ausgewählt.');
    return api.verifyPasskey(passkey.toJson());
  }

  void showError(String text) {
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(28),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 440),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const Icon(Icons.music_note_rounded, size: 84, color: Color(0xff1ed760)),
                  const Text('HBC Musik Client', textAlign: TextAlign.center, style: TextStyle(fontSize: 27, fontWeight: FontWeight.bold)),
                  const SizedBox(height: 42),
                  TextField(controller: userController, autofillHints: const [AutofillHints.username], decoration: const InputDecoration(labelText: 'User-ID', prefixIcon: Icon(Icons.person_outline))),
                  const SizedBox(height: 14),
                  TextField(controller: secretController, obscureText: true, autofillHints: const [AutofillHints.password], decoration: const InputDecoration(labelText: 'User-Secret', prefixIcon: Icon(Icons.lock_outline))),
                  const SizedBox(height: 22),
                  FilledButton.icon(onPressed: busy ? null : () => execute(() => api.login(userController.text.trim(), secretController.text)), icon: const Icon(Icons.login), label: const Text('Mit User-Secret anmelden')),
                  const Padding(padding: EdgeInsets.symmetric(vertical: 16), child: Row(children: [Expanded(child: Divider()), Padding(padding: EdgeInsets.symmetric(horizontal: 12), child: Text('oder')), Expanded(child: Divider())])),
                  OutlinedButton.icon(onPressed: busy ? null : () => execute(passkeyLogin), icon: const Icon(Icons.key), label: const Text('Mit Passkey anmelden')),
                  if (busy) const Padding(padding: EdgeInsets.all(20), child: Center(child: CircularProgressIndicator())),
                ]),
              ),
            ),
          ),
        ),
      );
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.api, required this.userId});
  final HbcApi api;
  final String userId;
  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int index = 0;
  Map<String, dynamic> player = const {};
  List<dynamic> playlists = const [];
  List<dynamic> serverPlaylists = const [];
  bool loading = false;

  @override
  void initState() { super.initState(); refreshPlayer(); }

  Future<void> run(Future<void> Function() operation) async {
    setState(() => loading = true);
    try { await operation(); } catch (error) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(error.toString())));
    } finally { if (mounted) setState(() => loading = false); }
  }

  Future<void> refreshPlayer() => run(() async { player = await widget.api.player(); if (mounted) setState(() {}); });
  Future<void> action(String value) => run(() async {
    await widget.api.playerAction(value, value: value == 'repeat' ? 'context' : null);
    player = await widget.api.player();
    if (mounted) setState(() {});
  });

  Widget playerPage() {
    final item = Map<String, dynamic>.from((player['item'] ?? player) as Map? ?? const {});
    final artists = (item['artists'] as List? ?? const []).map((a) => a is Map ? a['name'] : a).join(', ');
    final images = ((item['album'] as Map?)?['images'] as List? ?? const []);
    final imageUrl = images.isEmpty ? null : (images.first as Map?)?['url']?.toString();
    return RefreshIndicator(onRefresh: refreshPlayer, child: ListView(padding: const EdgeInsets.all(24), children: [
      const Text('Aktuelle Wiedergabe', textAlign: TextAlign.center, style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
      const SizedBox(height: 32),
      AspectRatio(aspectRatio: 1, child: Card(clipBehavior: Clip.antiAlias, child: imageUrl == null ? const Icon(Icons.music_note, size: 120) : Image.network(imageUrl, fit: BoxFit.cover, errorBuilder: (_, __, ___) => const Icon(Icons.music_note, size: 120)))),
      const SizedBox(height: 20),
      Text(item['name']?.toString() ?? 'Keine Wiedergabe', textAlign: TextAlign.center, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.bold)),
      Text(artists, textAlign: TextAlign.center),
      const SizedBox(height: 20),
      Row(mainAxisAlignment: MainAxisAlignment.spaceEvenly, children: [
        IconButton(iconSize: 36, onPressed: () => action('previous'), icon: const Icon(Icons.skip_previous)),
        FilledButton.tonal(onPressed: () => action(player['is_playing'] == true ? 'pause' : 'play'), child: Icon(player['is_playing'] == true ? Icons.pause : Icons.play_arrow, size: 42)),
        IconButton(iconSize: 36, onPressed: () => action('next'), icon: const Icon(Icons.skip_next)),
        IconButton(onPressed: () => action('repeat'), icon: const Icon(Icons.repeat)),
      ]),
    ]));
  }

  Widget listPage(bool server) => Column(children: [
    Expanded(child: ListView.builder(itemCount: server ? serverPlaylists.length : playlists.length, itemBuilder: (_, i) {
      final value = (server ? serverPlaylists : playlists)[i];
      final title = value is Map ? value['name']?.toString() ?? value.toString() : value.toString().split('•|•').first;
      return ListTile(leading: const Icon(Icons.queue_music), title: Text(title), subtitle: value is Map ? Text(value['owner']?['display_name']?.toString() ?? '') : null);
    })),
    Padding(padding: const EdgeInsets.all(16), child: FilledButton.icon(onPressed: () => run(() async { if (server) { serverPlaylists = await widget.api.serverPlaylists(); } else { playlists = await widget.api.playlists(); } if (mounted) setState(() {}); }), icon: const Icon(Icons.refresh), label: Text(server ? 'Server-Playlists laden' : 'Playlists laden'))),
  ]);

  Future<void> registerPasskey() async => run(() async {
    final options = await widget.api.passkeyRegistrationOptions(widget.userId);
    final credential = await credentialManager.savePasskeyCredentials(request: CredentialCreationOptions.fromJson(options));
    await widget.api.finishRegistration(credential.toJson());
    if (mounted) ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Passkey wurde erstellt.')));
  });

  Widget settingsPage() => ListView(padding: const EdgeInsets.all(16), children: [
    ListTile(leading: const CircleAvatar(child: Icon(Icons.person)), title: Text(widget.userId), subtitle: const Text('Angemeldet')),
    Card(child: Column(children: [
      ListTile(leading: const Icon(Icons.key), title: const Text('Passkey erstellen'), subtitle: const Text('Im Credential Manager dieses Geräts speichern'), onTap: registerPasskey),
      ListTile(leading: const Icon(Icons.chat), title: const Text('Webchat öffnen'), onTap: () => launchUrl(Uri.parse('${widget.api.baseUrl}/webchat?caller=in-app&client-id=${Uri.encodeComponent(widget.userId)}'), mode: LaunchMode.externalApplication)),
      ListTile(leading: const Icon(Icons.info_outline), title: const Text('Version 4.0.7'), subtitle: Text(widget.api.baseUrl)),
    ])),
    OutlinedButton.icon(onPressed: () => Navigator.pushAndRemoveUntil(context, MaterialPageRoute(builder: (_) => const LoginPage()), (_) => false), icon: const Icon(Icons.logout), label: const Text('Abmelden')),
  ]);

  @override
  Widget build(BuildContext context) {
    final pages = [playerPage(), listPage(false), listPage(true), settingsPage()];
    return Scaffold(
      appBar: AppBar(title: const Text('HBC Musik Client'), actions: [if (loading) const Padding(padding: EdgeInsets.all(18), child: SizedBox.square(dimension: 18, child: CircularProgressIndicator(strokeWidth: 2)))]),
      body: IndexedStack(index: index, children: pages),
      bottomNavigationBar: NavigationBar(selectedIndex: index, onDestinationSelected: (value) => setState(() => index = value), destinations: const [
        NavigationDestination(icon: Icon(Icons.music_note), label: 'Player'), NavigationDestination(icon: Icon(Icons.library_music), label: 'Playlists'), NavigationDestination(icon: Icon(Icons.cloud), label: 'Server'), NavigationDestination(icon: Icon(Icons.settings), label: 'Einstellungen'),
      ]),
    );
  }
}
