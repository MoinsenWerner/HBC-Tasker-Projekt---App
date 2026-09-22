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
  String recoveredSecret = '';
  final http.Client client;
  String? _cookie;

  Future<dynamic> request(String method, String path, {Object? body, bool form = false}) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (token.isNotEmpty) headers['Authorization'] = token;
    if (_cookie != null) headers['Cookie'] = _cookie!;
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
    final setCookie = response.headers['set-cookie'];
    if (setCookie != null) _cookie = setCookie.split(';').first;
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

  Future<Map<String, dynamic>> passkeyLoginOptions(String userId) async {
    final data = Map<String, dynamic>.from(await request('POST', '/api/authenticate/options', body: {'username': userId}) as Map);
    return Map<String, dynamic>.from((data['publicKey'] ?? data) as Map);
  }

  Future<Map<String, dynamic>> passkeyRegistrationOptions(String userId, String secret) async {
    final data = Map<String, dynamic>.from(await request('POST', '/api/register/options', body: {'username': userId, 'password': secret, 'type': 'fingerprint'}) as Map);
    return Map<String, dynamic>.from((data['publicKey'] ?? data) as Map);
  }

  Future<String> verifyPasskey(Map<String, dynamic> credential) async {
    final data = await request('POST', '/api/authenticate/verify', body: credential) as Map;
    final username = data['username'];
    final password = data['password'];
    if (username == null || password == null) throw const ApiException('Der Passkey-Vault hat keine Zugangsdaten geliefert.');
    recoveredSecret = password.toString();
    return login(username.toString(), password.toString());
  }

  Future<void> finishRegistration(Map<String, dynamic> credential) =>
      request('POST', '/api/register/verify', body: credential);

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
