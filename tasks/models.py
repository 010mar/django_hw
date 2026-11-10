import re
import uuid

from django.conf import settings
from django.core.validators import FileExtensionValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.urls import reverse

IMAGE_TOKEN_PATTERN = re.compile(r'\[\[img:([0-9a-fA-F-]{36})\]\]')
ALLOWED_ATTACHMENT_EXTENSIONS = ('xls', 'ods', 'txt')


class TaskBank(models.Model):
    name = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='task_banks',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создана')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлена')

    class Meta:
        verbose_name = 'База задач'
        verbose_name_plural = 'Базы задач'
        ordering = ('created_at',)

    def __str__(self):
        return self.name

    @property
    def task_count(self) -> int:
        return self.tasks.count()


class Topic(models.Model):
    bank = models.ForeignKey(
        TaskBank,
        on_delete=models.CASCADE,
        related_name='topics',
        verbose_name='База задач',
    )
    name = models.CharField(max_length=255, verbose_name='Название')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создана')

    class Meta:
        verbose_name = 'Тема'
        verbose_name_plural = 'Темы'
        ordering = ('order', 'name')
        unique_together = ('bank', 'name')

    def __str__(self):
        return self.name


class Task(models.Model):
    class Type(models.TextChoices):
        TEXT = 'text', 'Текстовая'
        GAP = 'gap', 'Пропуски'
        PROGRAMMING = 'programming', 'Программирование'

    class Difficulty(models.TextChoices):
        EASY = 'easy', 'Лёгкая'
        MEDIUM = 'medium', 'Средняя'
        HARD = 'hard', 'Сложная'

    class AnswerMode(models.TextChoices):
        CHOICE = 'choice', 'Выбор ответа'
        SHORT = 'short', 'Краткий ответ'

    class Language(models.TextChoices):
        PYTHON = 'python', 'Python'

    class Source(models.TextChoices):
        AUTHOR = 'author', 'Авторская'
        KOMPEGE = 'kompege', 'Kompege'
        YANDEX = 'yandex', 'Yandex'
        KPOLYAKOV = 'kpolyakov', 'Kpolyakov'
        OTHER = 'other', 'Другое'

    bank = models.ForeignKey(
        TaskBank,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='tasks',
        verbose_name='База задач',
    )
    topic = models.ForeignKey(
        Topic,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='tasks',
        verbose_name='Тема',
    )
    related_tasks = models.ManyToManyField(
        'self',
        blank=True,
        symmetrical=True,
        verbose_name='Связанные задачи',
        help_text='Другие задачи, связанные с этой (например, вопросы к одному тексту)',
    )
    task_number = models.CharField(
        max_length=32,
        blank=True,
        verbose_name='Номер задачи',
        help_text='Генерируется автоматически: номер_темы_порядковый_номер',
    )
    source = models.CharField(
        max_length=16,
        choices=Source.choices,
        default=Source.AUTHOR,
        verbose_name='Источник задачи',
    )
    type = models.CharField(
        max_length=16,
        choices=Type.choices,
        default=Type.TEXT,
        verbose_name='Тип задачи',
    )
    difficulty = models.CharField(
        max_length=8,
        choices=Difficulty.choices,
        default=Difficulty.MEDIUM,
        verbose_name='Сложность',
    )
    points = models.PositiveIntegerField(
        default=1,
        verbose_name='Баллы',
        help_text='Сколько баллов даёт задача',
    )
    case_sensitive = models.BooleanField(
        default=False,
        verbose_name='Регистр ответа должен совпадать',
    )
    show_cell_results = models.BooleanField(
        default=False,
        verbose_name='Показывать верные и ошибочные ячейки',
    )
    score_by_cells = models.BooleanField(
        default=False,
        verbose_name='Оценка зависит от числа верных ячеек',
    )
    title = models.CharField(max_length=255, verbose_name='Название')
    body = models.TextField(blank=True, verbose_name='Условие')
    image = models.ImageField(
        upload_to='tasks/',
        blank=True,
        null=True,
        verbose_name='Иллюстрация',
        help_text='Необязательная иллюстрация к условию',
    )

    answer_mode = models.CharField(
        max_length=8,
        choices=AnswerMode.choices,
        default=AnswerMode.SHORT,
        verbose_name='Тип ответа',
        help_text='Только для текстовых задач',
    )
    correct_answer = models.CharField(
        max_length=500,
        blank=True,
        verbose_name='Правильный ответ',
        help_text='Для краткого ответа (сравнение строгое, без учёта регистра)',
    )

    language = models.CharField(
        max_length=16,
        choices=Language.choices,
        default=Language.PYTHON,
        verbose_name='Язык программирования',
    )
    time_limit_ms = models.PositiveIntegerField(
        default=1000,
        verbose_name='Лимит времени, мс',
    )
    memory_limit_mb = models.PositiveIntegerField(
        default=128,
        verbose_name='Лимит памяти, МБ',
    )

    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='created_tasks',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создана')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлена')

    class Meta:
        verbose_name = 'Задача'
        verbose_name_plural = 'Задачи'
        ordering = ('-created_at',)

    def __str__(self):
        return self.title

    @property
    def type_verbose(self) -> str:
        return self.get_type_display()

    @property
    def difficulty_verbose(self) -> str:
        return self.get_difficulty_display()

    def get_absolute_url(self) -> str:
        if self.bank_id:
            return reverse('bank_task_detail', args=[self.bank_id, self.pk])
        return reverse('task_detail', args=[self.pk])

    def get_edit_url(self) -> str:
        if self.bank_id:
            return reverse('bank_task_edit', args=[self.bank_id, self.pk])
        return reverse('task_edit', args=[self.pk])

    def get_delete_url(self) -> str:
        if self.bank_id:
            return reverse('bank_task_delete', args=[self.bank_id, self.pk])
        return reverse('task_delete', args=[self.pk])

    def is_short_answer_correct(self, answer: str) -> bool:
        expected = self.correct_answer.strip()
        given = (answer or '').strip()
        if not self.case_sensitive:
            expected = expected.lower()
            given = given.lower()
        return expected == given

    @property
    def gap_blocks(self):
        return list(self.blocks.filter(kind='gap'))

    @property
    def gap_numbers(self) -> list[int]:
        return list(range(1, len(self.gap_blocks) + 1))

    def is_gap_answer_correct(self, number: int, answer: str) -> bool:
        blocks = self.gap_blocks
        if 1 <= number <= len(blocks):
            return blocks[number - 1].is_correct(
                answer, case_sensitive=self.case_sensitive,
            )
        return False


class TaskBlock(models.Model):
    class Kind(models.TextChoices):
        TEXT = 'text', 'Текст'
        GAP = 'gap', 'Пропуск'

    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='blocks',
        verbose_name='Задача',
    )
    kind = models.CharField(
        max_length=8,
        choices=Kind.choices,
        default=Kind.TEXT,
        verbose_name='Тип блока',
    )
    text = models.TextField(blank=True, verbose_name='Текст')
    answers = models.TextField(
        blank=True,
        verbose_name='Правильные ответы',
        help_text='По одному варианту в строке, регистр не учитывается',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        verbose_name = 'Блок задания'
        verbose_name_plural = 'Блоки задания'
        ordering = ('order', 'id')

    def __str__(self):
        return f'{self.task.title} — {self.get_kind_display()} {self.order}'

    @property
    def accepted_answers(self) -> list[str]:
        return [line.strip() for line in self.answers.splitlines() if line.strip()]

    def is_correct(self, answer: str, case_sensitive: bool = False) -> bool:
        normalized = (answer or '').strip()
        if not normalized:
            return False
        if case_sensitive:
            return normalized in self.accepted_answers
        normalized = normalized.lower()
        return any(
            normalized == accepted.lower() for accepted in self.accepted_answers
        )


class TaskImage(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='inline_images',
        verbose_name='Задача',
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='uploaded_task_images',
        verbose_name='Автор',
    )
    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name='Токен',
    )
    image = models.ImageField(
        upload_to='tasks/inline/%Y/%m/',
        verbose_name='Изображение',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Загружено')

    class Meta:
        verbose_name = 'Изображение к условию'
        verbose_name_plural = 'Изображения к условию'
        ordering = ('created_at',)

    def __str__(self):
        return f'Изображение {self.token}'

    @property
    def marker(self) -> str:
        return f'[[img:{self.token}]]'


@receiver(post_delete, sender=TaskImage)
def delete_task_image_file(sender, instance, **kwargs):
    if instance.image:
        instance.image.delete(save=False)


class TaskAttachment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='attachments',
        verbose_name='Задача',
    )
    file = models.FileField(
        upload_to='tasks/files/%Y/%m/',
        validators=[
            FileExtensionValidator(
                allowed_extensions=list(ALLOWED_ATTACHMENT_EXTENSIONS)
            )
        ],
        verbose_name='Файл',
    )
    original_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name='Имя файла',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Загружен')

    class Meta:
        verbose_name = 'Файл к задаче'
        verbose_name_plural = 'Файлы к задаче'
        ordering = ('created_at',)

    def __str__(self):
        return self.filename

    @property
    def filename(self) -> str:
        return self.original_name or self.file.name.rsplit('/', 1)[-1]


@receiver(post_delete, sender=TaskAttachment)
def delete_task_attachment_file(sender, instance, **kwargs):
    if instance.file:
        instance.file.delete(save=False)


class AnswerOption(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='answer_options',
        verbose_name='Задача',
    )
    text = models.CharField(max_length=500, verbose_name='Вариант ответа')
    is_correct = models.BooleanField(default=False, verbose_name='Правильный')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        verbose_name = 'Вариант ответа'
        verbose_name_plural = 'Варианты ответа'
        ordering = ('order', 'id')

    def __str__(self):
        return self.text


class TestCase(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='test_cases',
        verbose_name='Задача',
    )
    input_data = models.TextField(blank=True, default='', verbose_name='Входные данные')
    expected_output = models.TextField(blank=True, default='', verbose_name='Ожидаемый вывод')
    is_public = models.BooleanField(
        default=True,
        verbose_name='Открытый тест',
        help_text='Открытые тесты видны ученику, закрытые — только для проверки',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        verbose_name = 'Тест'
        verbose_name_plural = 'Тесты'
        ordering = ('order', 'id')

    def __str__(self):
        return f'{self.task.title} — тест {self.pk}'


class Course(models.Model):
    title = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='courses',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлён')

    class Meta:
        verbose_name = 'Курс'
        verbose_name_plural = 'Курсы'
        ordering = ('created_at',)

    def __str__(self):
        return self.title

    @property
    def lesson_count(self) -> int:
        return sum(module.lessons.count() for module in self.modules.all())


class CourseModule(models.Model):
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='modules',
        verbose_name='Курс',
    )
    title = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    start_date = models.DateField(null=True, blank=True, verbose_name='Начало модуля')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')

    class Meta:
        verbose_name = 'Модуль курса'
        verbose_name_plural = 'Модули курса'
        ordering = ('order', 'id')

    def __str__(self):
        return f'{self.course.title} — {self.title}'

    @property
    def lesson_count(self) -> int:
        return self.lessons.count()


class Lesson(models.Model):
    module = models.ForeignKey(
        CourseModule,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='lessons',
        verbose_name='Модуль',
    )
    title = models.CharField(max_length=255, verbose_name='Название урока')
    description = models.TextField(blank=True, verbose_name='Описание')
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='created_lessons',
        verbose_name='Автор',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Обновлён')

    class Meta:
        verbose_name = 'Урок'
        verbose_name_plural = 'Уроки'
        ordering = ('-created_at',)

    def __str__(self):
        return self.title

    @property
    def task_entries(self):
        return self.entries.select_related('task')

    @property
    def tasks_ordered(self):
        return [entry.task for entry in self.task_entries]


class LessonTask(models.Model):
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.CASCADE,
        related_name='entries',
        verbose_name='Урок',
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='lesson_entries',
        verbose_name='Задача',
    )
    order = models.PositiveIntegerField(default=0, verbose_name='Порядок')

    class Meta:
        verbose_name = 'Задача урока'
        verbose_name_plural = 'Задачи урока'
        ordering = ('order', 'id')
        unique_together = ('lesson', 'task')

    def __str__(self):
        return f'{self.lesson.title} — {self.task.title}'
