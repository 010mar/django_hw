import base64
import json
import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from tasks.models import (
    Task,
    TaskAttachment,
    TaskBank,
    TaskBlock,
    TaskImage,
    Topic,
)

PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII=",
)


class ImportTasksCommandTests(TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temp_dir, True)
        self.media_root = self.temp_dir / "media"
        self.media_root.mkdir()
        self.override = override_settings(MEDIA_ROOT=str(self.media_root))
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.teacher = get_user_model().objects.create_user(
            username="teacher", password="pass12345", role="teacher",
        )
        (self.temp_dir / "images").mkdir()
        (self.temp_dir / "images" / "pic.png").write_bytes(PNG_BYTES)
        (self.temp_dir / "files").mkdir()
        (self.temp_dir / "files" / "data.txt").write_text(
            "input data", encoding="utf-8",
        )
        self.export_path = self.temp_dir / "export.json"
        self.write_export(self.build_payload())

    def write_export(self, payload):
        self.export_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )

    def build_payload(self, extra_tasks=None):
        tasks = [
            {
                "external_id": 1,
                "number": 5,
                "topic": "Задание 5",
                "comment": "Яндекс ЕГЭ",
                "difficulty": 1,
                "type": "text",
                "body": "Найдите ответ\n[[img:img_1]]",
                "images": [{"key": "img_1", "file": "images/pic.png"}],
                "attachments": [
                    {"file": "files/data.txt", "original_name": "data.txt"},
                ],
                "correct_answer": "42",
                "missing_answer": False,
            },
            {
                "external_id": 2,
                "number": 5,
                "topic": "Задание 5",
                "comment": "Демоверсия 2027",
                "difficulty": 0,
                "type": "gap",
                "field_count": 2,
                "body": "Заполните пропуски",
                "gaps": ["1", "2"],
                "images": [],
                "attachments": [],
                "missing_answer": False,
            },
        ]
        if extra_tasks:
            tasks.extend(extra_tasks)
        return {
            "bank": {"name": "CodEge ЕГЭ", "description": "Описание"},
            "topics": [
                {"name": "Задание 5", "order": 5},
                {"name": "Задание 26", "order": 26},
            ],
            "tasks": tasks,
        }

    def run_import(self, **options):
        options.setdefault("author", "teacher")
        options.setdefault("media_dir", str(self.temp_dir))
        options.setdefault("file", str(self.export_path))
        return call_command("import_tasks", **options, stdout=StringIO())

    def test_imports_text_task_with_image_and_attachment(self):
        self.run_import()
        bank = TaskBank.objects.get(name="CodEge ЕГЭ")
        self.assertEqual(bank.description, "Описание")
        self.assertEqual(bank.author, self.teacher)

        task = Task.objects.get(task_number="5_1")
        self.assertEqual(task.title, "5_1")
        self.assertEqual(task.type, Task.Type.TEXT)
        self.assertEqual(task.correct_answer, "42")
        self.assertEqual(task.difficulty, Task.Difficulty.MEDIUM)
        self.assertEqual(task.source, Task.Source.YANDEX)
        self.assertEqual(task.points, 1)
        self.assertNotIn("[[img:img_1]]", task.body)

        image = TaskImage.objects.get(task=task)
        self.assertIn(f"[[img:{image.token}]]", task.body)
        self.assertTrue(image.image.path.startswith(str(self.media_root)))
        self.assertTrue(Path(image.image.path).is_file())

        attachment = TaskAttachment.objects.get(task=task)
        self.assertEqual(attachment.original_name, "data.txt")
        self.assertTrue(Path(attachment.file.path).is_file())

    def test_imports_gap_task(self):
        self.run_import()
        task = Task.objects.get(task_number="5_2")
        self.assertEqual(task.type, Task.Type.GAP)
        self.assertEqual(task.correct_answer, "")
        answers = list(
            task.blocks.filter(kind=TaskBlock.Kind.GAP)
            .order_by("order")
            .values_list("answers", flat=True)
        )
        self.assertEqual(answers, ["1", "2"])

    def test_number_26_gets_two_points(self):
        extra = [{
            "external_id": 3,
            "number": 26,
            "topic": "Задание 26",
            "comment": "",
            "difficulty": 2,
            "type": "text",
            "body": "Задача 26",
            "images": [],
            "attachments": [],
            "correct_answer": "7",
            "missing_answer": False,
        }]
        self.write_export(self.build_payload(extra))
        self.run_import()
        task = Task.objects.get(task_number="26_1")
        self.assertEqual(task.points, 2)
        self.assertEqual(task.difficulty, Task.Difficulty.HARD)

    def test_requires_replace_for_non_empty_bank(self):
        self.run_import()
        with self.assertRaises(CommandError):
            self.run_import()
        self.assertEqual(Task.objects.count(), 2)
        self.run_import(replace=True)
        self.assertEqual(Task.objects.count(), 2)

    def test_skips_unanswered(self):
        payload = self.build_payload()
        payload["tasks"][0]["missing_answer"] = True
        payload["tasks"][0]["correct_answer"] = ""
        self.write_export(payload)
        self.run_import(skip_unanswered=True)
        self.assertEqual(Task.objects.count(), 1)
        task = Task.objects.get(task_number="5_1")
        self.assertEqual(task.type, Task.Type.GAP)

    def test_dry_run_creates_nothing(self):
        self.run_import(dry_run=True)
        self.assertFalse(TaskBank.objects.exists())
        self.assertFalse(Task.objects.exists())

    def test_filter_by_numbers(self):
        self.run_import(numbers="5")
        self.assertEqual(Task.objects.count(), 2)
        self.assertFalse(Topic.objects.filter(name="Задание 26").exists())
