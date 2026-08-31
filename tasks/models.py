from django.conf import settings
from django.db import models


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
        ordering = ('-created_at',)

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
        IMAGE = 'image', 'С картинкой'
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
        on_delete=models.SET_NULL,
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
    title = models.CharField(max_length=255, verbose_name='Название')
    body = models.TextField(blank=True, verbose_name='Условие')
    image = models.ImageField(
        upload_to='tasks/',
        blank=True,
        null=True,
        verbose_name='Изображение',
        help_text='Для задач с картинкой или иллюстрация к условию',
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
        on_delete=models.SET_NULL,
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

    def is_short_answer_correct(self, answer: str) -> bool:
        return self.correct_answer.strip().lower() == (answer or '').strip().lower()


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


class Lesson(models.Model):
    title = models.CharField(max_length=255, verbose_name='Название урока')
    description = models.TextField(blank=True, verbose_name='Описание')
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
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
