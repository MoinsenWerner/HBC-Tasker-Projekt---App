import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:hbc_musik_client/api.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  test('default API points at the project API', () {
    expect(HbcApi().baseUrl, 'https://api.plsreload.de');
  });

  test('API errors are user presentable', () {
    expect(const ApiException('Fehler').toString(), 'Fehler');
  });

  test('login posts form credentials to token route', () async {
    late http.Request captured;
    final api = HbcApi(client: MockClient((request) async {
      captured = request;
      return http.Response('{"access_token":"abc"}', 200, headers: {'content-type': 'application/json'});
    }));
    expect(await api.login('felix', 'secret'), 'Bearer abc');
    expect(captured.method, 'POST');
    expect(captured.url.path, '/token');
    expect(captured.headers['content-type'], startsWith('application/x-www-form-urlencoded'));
    expect(captured.bodyFields, containsPair('grant_type', 'client_credentials'));
    expect(captured.bodyFields, containsPair('client_id', 'felix'));
  });

  test('player uses documented methods', () async {
    final methods = <String>[];
    final api = HbcApi(client: MockClient((request) async {
      methods.add('${request.method} ${request.url.path}');
      return http.Response('{}', 200);
    }));
    await api.playerAction('play');
    await api.playerAction('next');
    await api.playerAction('repeat', value: 'context');
    expect(methods, ['PUT /player/play', 'POST /player/next', 'PUT /player/repeat/context']);
  });

  test('missing passkey endpoint is reported before posting', () async {
    final api = HbcApi(client: MockClient((request) async => http.Response('/player;/token', 200)));
    await expectLater(api.passkeyLoginOptions('felix'), throwsA(isA<ApiException>()));
  });

  test('archive contains all exported Tasker scenes', () async {
    final raw = await File('assets/tasker_manifest.json').readAsString();
    final archive = jsonDecode(raw) as Map<String, dynamic>;
    expect(archive['scenes'], hasLength(17));
    expect((archive['scenes'] as List).map((scene) => scene['name']), contains('HBC Startseite'));
  });
}
