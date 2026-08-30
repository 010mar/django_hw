from django.contrib.auth import get_user_model
from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from tasks.models import AnswerOption, Lesson, LessonTask, Task
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
        self.image_task = Task.objects.create(
            title='Фото', type=Task.Type.IMAGE, author=self.teacher,
        )
        self.class_group = ClassGroup.objects.create(title='9А', teacher=self.teacher)
        self.class_group.students.set([self.student, self.other_student])
        self.assignment = Assignment.objects.create(
            title='ДЗ №1', author=self.teacher, class_group=self.class_group,
        )
        self.assignment.tasks.set([self.choice_task, self.short_task, self.prog_task, self.image_task])
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

    def test_solve_image_pending(self):
        from io import BytesIO
        from PIL import Image

        buf = BytesIO()
        Image.new('RGB', (4, 4), color='red').save(buf, format='PNG')
        buf.seek(0)
        self.client.post(
            reverse('solve_task', args=[self.assignment.pk, self.image_task.pk]),
            {'image': buf},
        )
        sub = Submission.objects.get(task=self.image_task)
        self.assertEqual(sub.status, Submission.Status.PENDING)
        self.assertTrue(sub.image)

    def test_teacher_grades_image(self):
        sub = Submission.objects.create(
            assignment=self.assignment, task=self.image_task,
            student=self.student, status=Submission.Status.PENDING,
        )
        self.client.force_login(self.teacher)
        self.client.post(reverse('grade_submission', args=[sub.pk]), {'action': 'accepted'})
        sub.refresh_from_db()
        self.assertEqual(sub.status, Submission.Status.ACCEPTED)
        self.assertEqual(sub.graded_by, self.teacher)

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
