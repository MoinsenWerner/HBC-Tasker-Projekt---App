import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

class TaskerArchivePage extends StatefulWidget {
  const TaskerArchivePage({super.key});

  @override
  State<TaskerArchivePage> createState() => _TaskerArchivePageState();
}

class _TaskerArchivePageState extends State<TaskerArchivePage> {
  Map<String, dynamic>? archive;

  @override
  void initState() {
    super.initState();
    rootBundle.loadString('assets/tasker_manifest.json').then((value) {
      if (mounted) setState(() => archive = jsonDecode(value) as Map<String, dynamic>);
    });
  }

  @override
  Widget build(BuildContext context) {
    final data = archive;
    if (data == null) return const Scaffold(body: Center(child: CircularProgressIndicator()));
    return DefaultTabController(
      length: 3,
      child: Scaffold(
        appBar: AppBar(
          title: const Text('Vollständiger Tasker-Export'),
          bottom: const TabBar(tabs: [Tab(text: 'Szenen'), Tab(text: 'Tasks'), Tab(text: 'Profile')]),
        ),
        body: TabBarView(children: [
          _SceneList(scenes: List<Map<String, dynamic>>.from(data['scenes'] as List)),
          _TaskList(tasks: List<Map<String, dynamic>>.from(data['tasks'] as List)),
          ListView(children: [for (final profile in data['profiles'] as List) ListTile(leading: const Icon(Icons.bolt), title: Text(profile['name'] as String))]),
        ]),
      ),
    );
  }
}

class _SceneList extends StatelessWidget {
  const _SceneList({required this.scenes});
  final List<Map<String, dynamic>> scenes;

  @override
  Widget build(BuildContext context) => ListView.builder(
        itemCount: scenes.length,
        itemBuilder: (_, index) {
          final scene = scenes[index];
          return ExpansionTile(
            title: Text(scene['name'] as String),
            subtitle: Text('${(scene['elements'] as List).length} UI-Elemente'),
            children: [for (final element in scene['elements'] as List) _element(context, Map<String, dynamic>.from(element as Map))],
          );
        },
      );

  Widget _element(BuildContext context, Map<String, dynamic> element) {
    final type = element['type'] as String;
    final name = element['name'] as String;
    final text = (element['text'] as String).isEmpty ? name : element['text'] as String;
    switch (type) {
      case 'Button':
        return Padding(padding: const EdgeInsets.all(8), child: OutlinedButton(onPressed: () => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(name))), child: Text(text)));
      case 'EditText':
        return Padding(padding: const EdgeInsets.all(8), child: TextField(decoration: InputDecoration(labelText: name, hintText: text)));
      case 'CheckBox':
      case 'Switch':
        return CheckboxListTile(value: false, onChanged: (_) {}, title: Text(text));
      case 'Slider':
        return ListTile(title: Text(name), subtitle: Slider(value: 0, onChanged: (_) {}));
      case 'Spinner':
      case 'Picker':
        return ListTile(leading: const Icon(Icons.arrow_drop_down_circle), title: Text(name), subtitle: Text(text));
      case 'Image':
        return ListTile(leading: const Icon(Icons.image), title: Text(name));
      case 'Web':
        return ListTile(leading: const Icon(Icons.public), title: Text(name), subtitle: Text(text));
      default:
        return ListTile(leading: const Icon(Icons.text_fields), title: Text(text), subtitle: Text(name));
    }
  }
}

class _TaskList extends StatelessWidget {
  const _TaskList({required this.tasks});
  final List<Map<String, dynamic>> tasks;

  @override
  Widget build(BuildContext context) => ListView.builder(
        itemCount: tasks.length,
        itemBuilder: (_, index) {
          final task = tasks[index];
          return ExpansionTile(
            title: Text(task['name'] as String),
            subtitle: Text('${(task['actions'] as List).length} Aktionen'),
            children: [
              for (final raw in task['actions'] as List)
                Builder(builder: (_) {
                  final action = Map<String, dynamic>.from(raw as Map);
                  final args = List<String>.from(action['arguments'] as List);
                  return ListTile(
                    dense: true,
                    leading: CircleAvatar(child: Text('${action['code']}')),
                    title: Text((action['label'] as String).isEmpty ? (args.isEmpty ? 'Tasker-Aktion' : args.first) : action['label'] as String),
                    subtitle: Text(args.take(3).join(' · ')),
                  );
                }),
            ],
          );
        },
      );
}
