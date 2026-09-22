import 'dart:convert';

import 'package:http/http.dart' as http;

class ApiException implements Exception {
  const ApiException(this.message);
  final String message;
  @override
  String toString() => message;
}

class HbcApi {
  HbcApi({this.baseUrl = 'https://api.plsreload.de', this.token = ''});

  String baseUrl;
  String token;

  Future<dynamic> request(String method, String path, {Object? body}) async {
    final headers = <String, String>{'Accept': 'application/json'};
    if (token.isNotEmpty) headers['Authorization'] = token;
    if (body != null) headers['Content-Type'] = 'application/json';
    final uri = Uri.parse('${baseUrl.replaceFirst(RegExp(r'/$'), '')}/${path.replaceFirst(RegExp(r'^/'), '')}');
    late http.Response response;
    switch (method) {
      case 'POST':
        response = await http.post(uri, headers: headers, body: body == null ? null : jsonEncode(body));
      case 'PUT':
        response = await http.put(uri, headers: headers, body: body == null ? null : jsonEncode(body));
      default:
        response = await http.get(uri, headers: headers);
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
    final data = await request('POST', '/authorize', body: {'user_id': userId, 'user_secret': secret});
    if (data is! Map) throw const ApiException('Ungültige Antwort des Anmeldeservers.');
    final value = data['token'] ?? data['authorization'] ?? data['access_token'];
    if (value == null || value.toString().isEmpty) throw const ApiException('Der Server hat kein Token geliefert.');
    return value.toString().contains(' ') ? value.toString() : 'Bearer $value';
  }

  Future<Map<String, dynamic>> passkeyLoginOptions(String userId) async =>
      Map<String, dynamic>.from(await request('POST', '/passkeys/authentication/options', body: {'user_id': userId}) as Map);

  Future<Map<String, dynamic>> passkeyRegistrationOptions(String userId) async =>
      Map<String, dynamic>.from(await request('POST', '/passkeys/registration/options', body: {'user_id': userId}) as Map);

  Future<String> verifyPasskey(Map<String, dynamic> credential) async {
    final data = await request('POST', '/passkeys/authentication/verify', body: credential) as Map;
    final value = data['token'] ?? data['access_token'];
    if (value == null) throw const ApiException('Passkey konnte nicht bestätigt werden.');
    return value.toString().contains(' ') ? value.toString() : 'Bearer $value';
  }

  Future<void> finishRegistration(Map<String, dynamic> credential) =>
      request('POST', '/passkeys/registration/verify', body: credential);

  Future<Map<String, dynamic>> player() async => Map<String, dynamic>.from(await request('GET', '/player') as Map);
  Future<void> playerAction(String action) => request('POST', '/player/$action');

  Future<List<dynamic>> playlists() async {
    final data = await request('GET', '/playlists');
    return data is Map ? List<dynamic>.from(data['items'] ?? data['playlists'] ?? const []) : const [];
  }

  Future<List<dynamic>> serverPlaylists() async {
    final data = await request('GET', '/serverplaylists/list?num=all');
    if (data is String) return data.split('°|°').where((item) => item.isNotEmpty).toList();
    return data is Map ? List<dynamic>.from(data['items'] ?? const []) : const [];
  }
}
