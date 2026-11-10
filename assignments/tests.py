from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase as DjangoTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from tasks.models import (
    AnswerOption,
    Lesson,
    LessonTask,
    Task,
    TaskBlock,
)
from tasks.models import TestCase as TaskTestCase

from .models import Assignment, ClassGroup, Submission

User = get_user_model()


class AssignmentFlowTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.STUDENT,
        )
        self.choice_task = Task.objects.create(
            title='Выбор', type=Task.Type.TEXT, author=self.teacher,
            answer_mode=Task.AnswerMode.CHOICE,
        )
        self.option_ok = AnswerOption.objects.create(
            task=self.choice_task, text='8', is_correct=True, order=0,
        )
        AnswerOption.objects.create(task=self.choice_task, text='16', is_correct=False, order=1)
        self.short_task = Task.objects.create(
            title='Краткий', type=Task.Type.TEXT, author=self.teacher,
            answer_mode=Task.AnswerMode.SHORT, correct_answer='42',
        )
        self.prog_task = Task.objects.create(
            title='A+B', type=Task.Type.PROGRAMMING, author=self.teacher,
            time_limit_ms=1000, memory_limit_mb=128,
        )
        TaskTestCase.objects.create(
            task=self.prog_task, input_data='2 3\n', expected_output='5\n', is_public=True,
        )
        self.gap_task = Task.objects.create(
            title='Пропуски', type=Task.Type.GAP, author=self.teacher,
            body='Заполните пропуски.',
        )
        TaskBlock.objects.create(
            task=self.gap_task, kind=TaskBlock.Kind.TEXT, text='2 + 2 = ', order=0,
        )
        TaskBlock.objects.create(
            task=self.gap_task, kind=TaskBlock.Kind.GAP, answers='4\nчетыре', order=1,
        )
        TaskBlock.objects.create(
            task=self.gap_task, kind=TaskBlock.Kind.TEXT, text=', а 3 × 3 = ', order=2,
        )
        TaskBlock.objects.create(
            task=self.gap_task, kind=TaskBlock.Kind.GAP, answers='9', order=3,
        )
        self.class_group = ClassGroup.objects.create(title='9А', teacher=self.teacher)
        self.class_group.students.set([self.student, self.other_student])
        self.assignment = Assignment.objects.create(
            title='ДЗ №1', author=self.teacher, class_group=self.class_group,
        )
        self.assignment.tasks.set([self.choice_task, self.short_task, self.prog_task, self.gap_task])
        self.client.force_login(self.student)

    def test_effective_students_from_class(self):
        self.assertEqual(
            set(self.assignment.effective_students),
            {self.student, self.other_student},
        )

    def test_student_sees_assignment(self):
        response = self.client.get(reverse('my_assignments'))
        self.assertContains(response, 'ДЗ №1')

    def test_other_student_not_in_class(self):
        stranger = User.objects.create_user(username='stranger', password='x', role=User.Role.STUDENT)
        self.client.force_login(stranger)
        response = self.client.get(reverse('my_assignments'))
        self.assertNotContains(response, 'ДЗ №1')

    def test_solve_choice_correct(self):
        response = self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.choice_task.pk]),
            {'answer_option': self.option_ok.pk},
        )
        self.assertEqual(response.status_code, 302)
        sub = Submission.objects.get(task=self.choice_task)
        self.assertEqual(sub.status, Submission.Status.CORRECT)
        self.assertEqual(sub.answer_option, self.option_ok)

    def test_solve_choice_wrong(self):
        wrong = self.choice_task.answer_options.filter(is_correct=False).first()
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.choice_task.pk]),
            {'answer_option': wrong.pk},
        )
        sub = Submission.objects.get(task=self.choice_task)
        self.assertEqual(sub.status, Submission.Status.INCORRECT)

    def test_solve_short_answer(self):
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.short_task.pk]),
            {'answer_text': ' 42 '},
        )
        sub = Submission.objects.get(task=self.short_task)
        self.assertEqual(sub.status, Submission.Status.CORRECT)
        self.assertEqual(sub.answer_text, ' 42 ')

    def test_solve_programming_ok(self):
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.prog_task.pk]),
            {'code': 'a, b = map(int, input().split())\nprint(a + b)\n'},
        )
        sub = Submission.objects.get(task=self.prog_task)
        self.assertEqual(sub.status, Submission.Status.OK, sub.details)

    def test_solve_programming_wa(self):
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.prog_task.pk]),
            {'code': 'print(0)\n'},
        )
        sub = Submission.objects.get(task=self.prog_task)
        self.assertEqual(sub.status, Submission.Status.WA)

    def test_solve_programming_without_tests_is_not_accepted(self):
        bare_task = Task.objects.create(
            title='Без тестов', type=Task.Type.PROGRAMMING, author=self.teacher,
        )
        self.assignment.tasks.add(bare_task)
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, bare_task.pk]),
            {'code': 'print(1)\n'},
        )
        sub = Submission.objects.get(task=bare_task)
        self.assertEqual(sub.status, Submission.Status.WA)
        self.assertIn('не настроены тесты', sub.details)

    def test_solve_gap_correct(self):
        response = self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.gap_task.pk]),
            {'gap_1': '4', 'gap_2': '9'},
        )
        self.assertEqual(response.status_code, 302)
        sub = Submission.objects.get(task=self.gap_task)
        self.assertEqual(sub.status, Submission.Status.CORRECT)
        self.assertEqual(sub.gap_answers, {'1': '4', '2': '9'})

    def test_solve_gap_incorrect(self):
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.gap_task.pk]),
            {'gap_1': '4', 'gap_2': '8'},
        )
        sub = Submission.objects.get(task=self.gap_task)
        self.assertEqual(sub.status, Submission.Status.INCORRECT)
        self.assertEqual(sub.gap_answers, {'1': '4', '2': '8'})

    def test_solve_gap_accepts_any_listed_answer(self):
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.gap_task.pk]),
            {'gap_1': 'Четыре', 'gap_2': '9'},
        )
        sub = Submission.objects.get(task=self.gap_task)
        self.assertEqual(sub.status, Submission.Status.CORRECT)

    def test_solve_page_renders_gap_inputs(self):
        response = self.client.get(
            reverse('solve_task', args=[self.assignment.pk, self.gap_task.pk]),
        )
        self.assertContains(response, 'name="gap_1"')
        self.assertContains(response, 'name="gap_2"')
        self.assertContains(response, 'Введите или скопируйте свой ответ в поля таблицы')
        self.assertContains(response, 'Сохранить ответ')
        self.assertContains(response, 'Очистить')
        self.assertNotContains(response, 'Пропуск 1')

    def test_solve_page_renders_text_breaks(self):
        text_block = self.gap_task.blocks.get(order=0)
        text_block.text = '2 + 2 = <br>'
        text_block.save(update_fields=['text'])
        response = self.client.get(
            reverse('solve_task', args=[self.assignment.pk, self.gap_task.pk]),
        )
        self.assertIn('2 + 2 = <br>', response.content.decode())

    def test_teacher_grades_image(self):
        sub = Submission.objects.create(
            assignment=self.assignment, task=self.gap_task,
            student=self.student, status=Submission.Status.PENDING,
        )
        self.client.force_login(self.teacher)
        self.client.post(reverse('grade_submission', args=[sub.pk]), {'action': 'accepted'})
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.ACCEPTED)
        self.assertEqual(sub.graded_by, self.teacher)

    def test_grade_page_shows_attempt_numbers(self):
        first = Submission.objects.create(
            assignment=self.assignment, task=self.gap_task,
            student=self.student, status=Submission.Status.PENDING,
        )
        Submission.objects.filter(pk=first.pk).update(
            created_at=timezone.now() - timedelta(minutes=1),
        )
        Submission.objects.create(
            assignment=self.assignment, task=self.gap_task,
            student=self.student, status=Submission.Status.PENDING,
        )
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('assignment_grade', args=[self.assignment.pk]),
        )
        self.assertContains(response, 'Попытка №1')
        self.assertContains(response, 'Попытка №2')

    def test_my_assignments_query_count_is_stable(self):
        self.client.force_login(self.student)
        with CaptureQueriesContext(connection) as single:
            self.client.get(reverse('my_assignments'))
        extra_task = Task.objects.create(title='Ещё', author=self.teacher)
        for index in range(4):
            extra = Assignment.objects.create(
                title=f'ДЗ {index}', author=self.teacher,
                class_group=self.class_group,
            )
            extra.tasks.set([extra_task])
        with CaptureQueriesContext(connection) as multiple:
            self.client.get(reverse('my_assignments'))
        self.assertEqual(len(single), len(multiple))

    def test_teacher_only_views(self):
        self.client.force_login(self.student)
        for url_name, args in [
            ('class_list', []),
            ('class_create', []),
            ('assignment_create', []),
            ('assignment_list', []),
        ]:
            response = self.client.get(reverse(url_name, args=args))
            self.assertRedirects(response, reverse('home'))


class AssignmentCreateViewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.task = Task.objects.create(title='Задача', author=self.teacher)
        self.lesson = Lesson.objects.create(title='Урок', author=self.teacher)
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        self.class_group = ClassGroup.objects.create(title='9Б', teacher=self.teacher)
        self.class_group.students.set([self.student])
        self.client.force_login(self.teacher)

    def test_create_assignment_via_form(self):
        response = self.client.post(reverse('assignment_create'), {
            'title': 'ДЗ 2',
            'description': '',
            'class_group': self.class_group.pk,
            'students': [],
            'tasks': [self.task.pk],
            'lesson': '',
            'deadline': '2026-12-31T18:00',
        })
        assignment = Assignment.objects.get(title='ДЗ 2')
        self.assertRedirects(response, reverse('assignment_detail', args=[assignment.pk]))
        self.assertEqual(assignment.tasks.count(), 1)
        self.assertEqual(assignment.deadline.year, 2026)

    def test_create_assignment_requires_target(self):
        response = self.client.post(reverse('assignment_create'), {
            'title': 'Без класса',
            'class_group': '',
            'students': [],
            'tasks': [self.task.pk],
            'lesson': '',
            'deadline': '',
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Assignment.objects.filter(title='Без класса').exists())


class AnonymousAccessTests(DjangoTestCase):
    def test_my_assignments_requires_login(self):
        response = self.client.get(reverse('my_assignments'))
        self.assertRedirects(
            response,
            f'{reverse("account_login")}?next={reverse("my_assignments")}',
        )

    def test_solve_views_require_login(self):
        for url in (
            reverse('assignment_solve', args=[1]),
            reverse('solve_task', args=[1, 1]),
        ):
            response = self.client.get(url)
            self.assertRedirects(response, f'{reverse("account_login")}?next={url}')


class TaskPreviewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.task = Task.objects.create(
            title='Выбор', type=Task.Type.TEXT, author=self.teacher,
            answer_mode=Task.AnswerMode.CHOICE,
        )
        self.option = AnswerOption.objects.create(
            task=self.task, text='8', is_correct=True, order=0,
        )

    def test_teacher_previews_own_task_as_student(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('task_preview', args=[self.task.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Просмотр как ученик')
        self.assertContains(response, self.option.text)
        self.assertContains(response, 'disabled')
        self.assertNotContains(response, 'Отправить')

    def test_student_cannot_preview_task(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('task_preview', args=[self.task.pk]))
        self.assertRedirects(response, reverse('home'))

    def test_other_teacher_cannot_preview_task(self):
        other = User.objects.create_user(
            username='other_teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.client.force_login(other)
        response = self.client.get(reverse('task_preview', args=[self.task.pk]))
        self.assertEqual(response.status_code, 404)
