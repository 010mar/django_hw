import json
import re
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from tasks.models import (
    Task,
    TaskAttachment,
    TaskBank,
    TaskBlock,
    TaskImage,
    Topic,
)

DIFFICULTY_MAP = {
    0: Task.Difficulty.EASY,
    1: Task.Difficulty.MEDIUM,
    2: Task.Difficulty.HARD,
}

POINTS_BY_NUMBER = {26: 2, 27: 2}


def map_source(comment: str) -> str:
    text = (comment or "").lower()
    if "яндекс" in text:
        return Task.Source.YANDEX
    if "поляков" in text:
        return Task.Source.KPOLYAKOV
    if "kompege" in text or "компеге" in text:
        return Task.Source.KOMPEGE
    return Task.Source.OTHER


class Command(BaseCommand):
    help = "Импортирует задачи из JSON-экспорта codege.ru"

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True, help="Путь к export.json")
        parser.add_argument("--media-dir", help="Папка с files/ и images/")
        parser.add_argument("--bank", help="Имя базы задач")
        parser.add_argument("--description", help="Описание базы задач")
        parser.add_argument(
            "--author", help="Логин учителя-автора (по умолчанию первый учитель)",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            help="Удалить существующие задачи этой базы перед импортом",
        )
        parser.add_argument(
            "--skip-unanswered",
            action="store_true",
            help="Пропускать задачи без правильного ответа",
        )
        parser.add_argument("--numbers", help="Только указанные номера: 5,6 или 1-9")
        parser.add_argument(
            "--limit", type=int, help="Импортировать не более N задач",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Только показать, что будет импортировано",
        )

    def handle(self, *args, **options):
        file_path = Path(options["file"]).expanduser().resolve()
        if not file_path.is_file():
            raise CommandError(f"Файл не найден: {file_path}")
        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise CommandError(f"Некорректный JSON: {exc}") from exc

        media_dir = (
            Path(options["media_dir"]).expanduser().resolve()
            if options["media_dir"]
            else file_path.parent
        )
        bank_name = (
            options["bank"]
            or (data.get("bank") or {}).get("name")
            or "CodEge ЕГЭ"
        )
        description = (
            options["description"]
            or (data.get("bank") or {}).get("description")
            or ""
        )
        tasks = self._filtered_tasks(data, options)
        if not tasks:
            raise CommandError("В экспорте нет подходящих задач.")

        author = self._resolve_author(options["author"])
        if options["dry_run"]:
            self._report_dry_run(tasks, media_dir)
            return

        bank = TaskBank.objects.filter(name=bank_name).first()
        if bank is None:
            bank = TaskBank.objects.create(
                name=bank_name, description=description, author=author,
            )
            self.stdout.write(f"Создана база задач «{bank_name}»")
        else:
            if bank.tasks.exists():
                if not options["replace"]:
                    raise CommandError(
                        f"База «{bank_name}» уже содержит "
                        f"{bank.tasks.count()} задач. "
                        "Добавьте --replace, чтобы заменить их.",
                    )
                deleted, _ = bank.tasks.all().delete()
                self.stdout.write(
                    f"Удалено старых объектов: {deleted} "
                    f"(задачи базы «{bank_name}»)",
                )
            if description and bank.description != description:
                bank.description = description
                bank.save(update_fields=["description"])

        topics = self._ensure_topics(bank, data.get("topics") or [], tasks)
        self._import_tasks(
            bank, author, media_dir, tasks, topics, options,
        )

    def _resolve_author(self, username):
        User = get_user_model()
        if username:
            author = User.objects.filter(username=username).first()
            if author is None:
                raise CommandError(f"Пользователь «{username}» не найден.")
            if author.role != User.Role.TEACHER:
                raise CommandError(f"Пользователь «{username}» не учитель.")
            return author
        author = User.objects.filter(role=User.Role.TEACHER).order_by("pk").first()
        if author is None:
            raise CommandError(
                "В системе нет учителей. Укажите --author <логин>.",
            )
        return author

    def _filtered_tasks(self, data, options):
        numbers = self._parse_numbers(options.get("numbers"))
        result = []
        for task in data.get("tasks") or []:
            number = task.get("number")
            if numbers and number not in numbers:
                continue
            if options["skip_unanswered"] and task.get("missing_answer"):
                continue
            result.append(task)
            if options.get("limit") and len(result) >= options["limit"]:
                break
        return result

    def _parse_numbers(self, value):
        if not value:
            return None
        numbers = set()
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = part.split("-", 1)
                numbers.update(range(int(start), int(end) + 1))
            else:
                numbers.add(int(part))
        return numbers

    def _ensure_topics(self, bank, topic_rows, tasks):
        used_names = {
            task.get("topic") or f"Задание {task.get('number')}"
            for task in tasks
        }
        rows = {
            row["name"]: row
            for row in topic_rows
            if row.get("name") in used_names
        }
        for task in tasks:
            name = task.get("topic") or f"Задание {task.get('number')}"
            rows.setdefault(name, {"name": name, "order": task.get("number") or 0})

        topics = {}
        for name, row in rows.items():
            topic, _ = Topic.objects.get_or_create(
                bank=bank,
                name=name,
                defaults={"order": row.get("order") or 0},
            )
            order = row.get("order") or 0
            if topic.order != order:
                topic.order = order
                topic.save(update_fields=["order"])
            topics[name] = topic
        return topics

    def _report_dry_run(self, tasks, media_dir):
        text_count = sum(1 for task in tasks if task.get("type") != "gap")
        gap_count = len(tasks) - text_count
        unanswered = sum(1 for task in tasks if task.get("missing_answer"))
        missing_files = 0
        for task in tasks:
            for item in (task.get("images") or []) + (task.get("attachments") or []):
                if not (media_dir / item["file"]).is_file():
                    missing_files += 1
        self.stdout.write(
            f"Задач: {len(tasks)} (текстовых {text_count}, с пропусками "
            f"{gap_count}); без ответа: {unanswered}; "
            f"отсутствующих файлов: {missing_files}",
        )

    def _import_tasks(self, bank, author, media_dir, tasks, topics, options):
        counters = {"created": 0, "skipped": 0, "missing_files": 0}
        sequences = {}
        for index, payload in enumerate(tasks, start=1):
            topic_name = payload.get("topic") or f"Задание {payload.get('number')}"
            topic = topics[topic_name]
            sequence = sequences.get(topic.pk, 0) + 1
            sequences[topic.pk] = sequence
            try:
                with transaction.atomic():
                    self._create_task(
                        bank, topic, author, media_dir, payload,
                        sequence, counters,
                    )
            except Exception as exc:  # noqa: BLE001
                counters["skipped"] += 1
                self.stderr.write(
                    f"Задача {payload.get('external_id')}: ошибка {exc}",
                )
                continue
            counters["created"] += 1
            if counters["created"] % 100 == 0:
                self.stdout.write(f"Импортировано: {counters['created']}")

        self.stdout.write(
            self.style.SUCCESS(
                f"Готово: создано {counters['created']}, "
                f"пропущено {counters['skipped']}, "
                f"не найдено файлов {counters['missing_files']}.",
            ),
        )

    def _create_task(
        self, bank, topic, author, media_dir, payload, sequence, counters,
    ):
        number = payload.get("number") or topic.order or 0
        task_number = f"{topic.order or number}_{sequence}"
        difficulty = DIFFICULTY_MAP.get(
            payload.get("difficulty"), Task.Difficulty.MEDIUM,
        )
        source = map_source(payload.get("comment"))
        task_type = Task.Type.GAP if payload.get("type") == "gap" else Task.Type.TEXT
        correct_answer = payload.get("correct_answer") or ""
        gaps = list(payload.get("gaps") or [])
        if task_type == Task.Type.TEXT and len(correct_answer) > 500:
            task_type = Task.Type.GAP
            gaps = [correct_answer]
            correct_answer = ""

        task = Task.objects.create(
            bank=bank,
            topic=topic,
            author=author,
            source=source,
            type=task_type,
            difficulty=difficulty,
            points=POINTS_BY_NUMBER.get(int(number), 1),
            answer_mode=Task.AnswerMode.SHORT,
            case_sensitive=False,
            task_number=task_number,
            title=task_number,
            body="",
            correct_answer=correct_answer if task_type == Task.Type.TEXT else "",
        )

        body = payload.get("body") or ""
        for image in payload.get("images") or []:
            source_path = media_dir / image["file"]
            if not source_path.is_file():
                counters["missing_files"] += 1
                body = body.replace(f"[[img:{image['key']}]]", "")
                continue
            with source_path.open("rb") as fh:
                task_image = TaskImage(task=task, author=author)
                task_image.image.save(source_path.name, File(fh), save=True)
            body = body.replace(
                f"[[img:{image['key']}]]", f"[[img:{task_image.token}]]",
            )
        body = re.sub(r"\[\[img:\w+\]\]", "", body)
        if body != task.body:
            task.body = body
            task.save(update_fields=["body"])

        for attachment in payload.get("attachments") or []:
            source_path = media_dir / attachment["file"]
            if not source_path.is_file():
                counters["missing_files"] += 1
                continue
            with source_path.open("rb") as fh:
                TaskAttachment.objects.create(
                    task=task,
                    original_name=(
                        attachment.get("original_name") or source_path.name
                    ),
                    file=File(fh, name=source_path.name),
                )

        if task_type == Task.Type.GAP:
            for order, answer in enumerate(gaps, start=1):
                TaskBlock.objects.create(
                    task=task,
                    kind=TaskBlock.Kind.GAP,
                    answers=answer or "",
                    order=order,
                )
