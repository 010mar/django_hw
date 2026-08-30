from django.conf import settings
from django.db import models

from tasks.models import AnswerOption, Lesson, Task


class ClassGroup(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='taught_class_groups',
        verbose_name='Учитель',
    )
    title = models.CharField(max_length=255, verbose_name='Название класса')
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='class_groups',
        blank=True,
        verbose_name='Ученики',
        limit_choices_to={'role': 'student'},
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создан')

    class Meta:
        verbose_name = 'Класс'
        verbose_name_plural = 'Классы'
        ordering = ('title',)

    def __str__(self):
        return self.title


class Assignment(models.Model):
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assignments',
        verbose_name='Учитель',
    )
    title = models.CharField(max_length=255, verbose_name='Название')
    description = models.TextField(blank=True, verbose_name='Описание')
    class_group = models.ForeignKey(
        ClassGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignments',
        verbose_name='Класс',
    )
    students = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='direct_assignments',
        blank=True,
        verbose_name='Ученики',
        limit_choices_to={'role': 'student'},
    )
    tasks = models.ManyToManyField(
        Task,
        related_name='assignments',
        blank=True,
        verbose_name='Задачи',
    )
    lesson = models.ForeignKey(
        Lesson,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assignments',
        verbose_name='Урок',
        help_text='Если урок указан, его задачи добавляются в задание',
    )
    deadline = models.DateTimeField(null=True, blank=True, verbose_name='Дедлайн')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Создано')

    class Meta:
        verbose_name = 'Задание'
        verbose_name_plural = 'Задания'
        ordering = ('-created_at',)

    def __str__(self):
        return self.title

    @property
    def effective_students(self):
        if self.class_group_id:
            students = self.class_group.students.all()
        else:
            students = self.students.all()
        return students.distinct().order_by('last_name', 'first_name', 'username')

    @property
    def tasks_ordered(self):
        if self.lesson_id:
            lesson_order = {
                entry.task_id: i
                for i, entry in enumerate(self.lesson.task_entries)
            }
            return sorted(
                self.tasks.all(),
                key=lambda t: lesson_order.get(t.pk, 10**9),
            )
        return self.tasks.all().order_by('title')

    def task_status(self, student, task):
        submissions = Submission.objects.filter(
            assignment=self, task=task, student=student,
        )
        if submissions.exists():
            return submissions.order_by('-created_at').first()
        return None


class Submission(models.Model):
    class Status(models.TextChoices):
        CORRECT = 'correct', 'Верно'
        INCORRECT = 'incorrect', 'Неверно'
        OK = 'ok', 'OK'
        WA = 'wa', 'Неправильный ответ'
        TLE = 'tle', 'Превышено время'
        RE = 're', 'Ошибка выполнения'
        CE = 'ce', 'Ошибка компиляции'
        PENDING = 'pending', 'На проверке'
        ACCEPTED = 'accepted', 'Зачтено'
        REJECTED = 'rejected', 'Не зачтено'

    SOLVED_STATUSES = (Status.CORRECT, Status.OK, Status.ACCEPTED)

    assignment = models.ForeignKey(
        Assignment,
        on_delete=models.CASCADE,
        related_name='submissions',
        verbose_name='Задание',
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name='submissions',
        verbose_name='Задача',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='submissions',
        verbose_name='Ученик',
    )
    answer_option = models.ForeignKey(
        AnswerOption,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='submissions',
        verbose_name='Выбранный вариант',
    )
    answer_text = models.CharField(max_length=500, blank=True, verbose_name='Краткий ответ')
    image = models.ImageField(
        upload_to='submissions/',
        blank=True,
        null=True,
        verbose_name='Изображение',
    )
    code = models.TextField(blank=True, verbose_name='Код решения')
    details = models.TextField(blank=True, verbose_name='Детали')
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        verbose_name='Статус',
    )
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='graded_submissions',
        verbose_name='Проверил',
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Отправлено')

    class Meta:
        verbose_name = 'Решение'
        verbose_name_plural = 'Решения'
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.student} — {self.task.title}'

    @property
    def is_solved(self):
        return self.status in self.SOLVED_STATUSES

    @property
    def attempt_number(self):
        return Submission.objects.filter(
            assignment=self.assignment,
            task=self.task,
            student=self.student,
            created_at__lte=self.created_at,
        ).count()
