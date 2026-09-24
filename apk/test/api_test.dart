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

  test('passkey options use the documented vault endpoint', () async {
    late http.Request captured;
    final api = HbcApi(client: MockClient((request) async {
      captured = request;
      return http.Response('{"publicKey":{"challenge":"abc"}}', 200);
    }));
    expect(await api.passkeyLoginOptions('felix'), containsPair('challenge', 'abc'));
    expect(captured.url.path, '/api/authenticate/options');
    expect(captured.body, contains('"username":"felix"'));
  });

  test('passkey challenge session cookie is retained for verification', () async {
    final requests = <http.Request>[];
    final api = HbcApi(client: MockClient((request) async {
      requests.add(request);
      if (requests.length == 1) {
        return http.Response('{"challenge":"abc"}', 200, headers: {'set-cookie': 'session=vault123; Secure; HttpOnly'});
      }
      return http.Response('{"username":"felix","password":"secret"}', 200);
    }));
    await api.passkeyLoginOptions('felix');
    await expectLater(api.verifyPasskey({'id': 'credential'}), throwsA(isA<ApiException>()));
    expect(requests[1].headers['Cookie'], 'session=vault123');
  });

  test('archive contains all exported Tasker scenes', () async {
    final raw = await File('assets/tasker_manifest.json').readAsString();
    final archive = jsonDecode(raw) as Map<String, dynamic>;
    expect(archive['scenes'], hasLength(17));
    expect((archive['scenes'] as List).map((scene) => scene['name']), contains('HBC Startseite'));
    final handled = (archive['scenes'] as List).expand((scene) => scene['elements'] as List).where((element) => (element['handlers'] as Map).isNotEmpty);
    expect(handled.length, greaterThan(50));
  });
}
