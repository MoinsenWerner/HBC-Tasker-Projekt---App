import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  const ApiException(this.message);
  final String message;
  @override
  String toString() => message;
}

class HbcApi {
  HbcApi({this.baseUrl = 'https://api.plsreload.de', this.token = '', http.Client? client}) : client = client ?? http.Client();

  String baseUrl;
  String token;
  String userId = '';
  final http.Client client;

  Future<dynamic> request(String method, String path, {Object? body, bool form = false}) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (token.isNotEmpty) headers['Authorization'] = token;
    if (body != null && !form) headers['Content-Type'] = 'application/json';
    final uri = Uri.parse('${baseUrl.replaceFirst(RegExp(r'/$'), '')}/${path.replaceFirst(RegExp(r'^/'), '')}');
    late http.Response response;
    switch (method) {
      case 'POST':
        response = await client.post(uri, headers: headers, body: body == null ? null : form ? body : jsonEncode(body));
      case 'PUT':
        response = await client.put(uri, headers: headers, body: body == null ? null : jsonEncode(body));
      default:
        response = await client.get(uri, headers: headers);
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(response.body.isEmpty ? 'HTTP ${response.statusCode}' : response.body);
    }
    if (response.body.isEmpty) return <String, dynamic>{};
    try {
      return jsonDecode(response.body);
    } on FormatException {
      return response.body;
    }
  }

  Future<String> login(String userId, String secret) async {
    final data = await request('POST', '/token', form: true, body: {
      'grant_type': 'client_credentials',
      'client_id': userId,
      'client_secret': secret,
    });
    if (data is! Map) throw const ApiException('Ungültige Antwort des Anmeldeservers.');
    final value = data['token'] ?? data['authorization'] ?? data['access_token'];
    if (value == null || value.toString().isEmpty) throw const ApiException('Der Server hat kein Token geliefert.');
    return value.toString().contains(' ') ? value.toString() : 'Bearer $value';
  }

  Future<void> requirePasskeyRoute(String route) async {
    final routes = await request('GET', '/routes?format=text');
    if (routes is! String || !routes.split(';').contains(route)) {
      throw const ApiException('Der HBC-Server bietet aktuell noch keine Passkey-API an. Bitte User-ID und User-Secret verwenden.');
    }
  }

  Future<Map<String, dynamic>> passkeyLoginOptions(String userId) async {
    await requirePasskeyRoute('/passkeys/authentication/options');
    return Map<String, dynamic>.from(await request('POST', '/passkeys/authentication/options', body: {'user_id': userId}) as Map);
  }

  Future<Map<String, dynamic>> passkeyRegistrationOptions(String userId) async {
    await requirePasskeyRoute('/passkeys/registration/options');
    return Map<String, dynamic>.from(await request('POST', '/passkeys/registration/options', body: {'user_id': userId}) as Map);
  }

  Future<String> verifyPasskey(Map<String, dynamic> credential) async {
    final data = await request('POST', '/passkeys/authentication/verify', body: credential) as Map;
    final value = data['token'] ?? data['access_token'];
    if (value == null) throw const ApiException('Passkey konnte nicht bestätigt werden.');
    return value.toString().contains(' ') ? value.toString() : 'Bearer $value';
  }

  Future<void> finishRegistration(Map<String, dynamic> credential) =>
      request('POST', '/passkeys/registration/verify', body: credential);

  Future<Map<String, dynamic>> player() async => Map<String, dynamic>.from(await request('GET', '/player') as Map);
  Future<void> playerAction(String action, {String? value}) {
    final method = switch (action) { 'play' || 'pause' || 'repeat' => 'PUT', 'next' || 'previous' => 'POST', _ => 'GET' };
    final suffix = value == null ? '' : '/${Uri.encodeComponent(value)}';
    return request(method, '/player/$action$suffix');
  }

  Future<List<dynamic>> playlists() async {
    final data = await request('GET', '/chat/share/playlists/${Uri.encodeComponent(userId)}');
    return data is Map ? List<dynamic>.from(data['eigene_playlists'] ?? const []) : const [];
  }

  Future<List<dynamic>> serverPlaylists() async {
    final data = await request('GET', '/serverplaylists/list?num=all');
    if (data is String) return data.split('°|°').where((item) => item.isNotEmpty).toList();
    return data is Map ? List<dynamic>.from(data['items'] ?? const []) : const [];
  }
}
