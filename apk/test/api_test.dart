import 'package:flutter_test/flutter_test.dart';
import 'package:hbc_musik_client/api.dart';

void main() {
  test('default API points at the project API', () {
    expect(HbcApi().baseUrl, 'https://api.plsreload.de');
  });

  test('API errors are user presentable', () {
    expect(const ApiException('Fehler').toString(), 'Fehler');
  });
}
