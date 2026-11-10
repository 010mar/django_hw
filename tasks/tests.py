import importlib
import os
import shutil
import tempfile
from decimal import Decimal
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase as DjangoTestCase
from django.test import override_settings
from django.urls import reverse
from PIL import Image as PILImage

from assignments.models import Submission

from .forms import TaskForm
from .models import (
    AnswerOption,
    Course,
    CourseModule,
    Lesson,
    LessonTask,
    Task,
    TaskAttachment,
    TaskBank,
    TaskBlock,
    TaskImage,
    Topic,
)
from .models import TestCase as TaskTestCase

User = get_user_model()


class TaskModelTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345'
        )

    def test_create_text_task(self):
        task = Task.objects.create(
            title='Сколько бит в байте?',
            type=Task.Type.TEXT,
            difficulty=Task.Difficulty.EASY,
            answer_mode=Task.AnswerMode.CHOICE,
            author=self.teacher,
        )
        AnswerOption.objects.create(task=task, text='8', is_correct=True, order=0)
        AnswerOption.objects.create(task=task, text='16', is_correct=False, order=1)
        self.assertEqual(task.type_verbose, 'Текстовая')
        self.assertEqual(task.difficulty_verbose, 'Лёгкая')
        self.assertEqual(task.answer_options.count(), 2)

    def test_create_programming_task_with_cases(self):
        task = Task.objects.create(
            title='Сумма двух чисел',
            type=Task.Type.PROGRAMMING,
            difficulty=Task.Difficulty.MEDIUM,
            author=self.teacher,
        )
        TaskTestCase.objects.create(task=task, input_data='2 3\n', expected_output='5\n', is_public=True)
        TaskTestCase.objects.create(task=task, input_data='10 20\n', expected_output='30\n', is_public=False)
        self.assertEqual(task.test_cases.count(), 2)

    def test_short_answer_strict_compare(self):
        task = Task.objects.create(
            title='Чему равно print(2**3)?',
            type=Task.Type.TEXT,
            answer_mode=Task.AnswerMode.SHORT,
            correct_answer='8',
        )
        self.assertTrue(task.is_short_answer_correct('8'))
        self.assertTrue(task.is_short_answer_correct(' 8 '))
        self.assertFalse(task.is_short_answer_correct('7'))

    def test_short_answer_case_sensitive(self):
        task = Task.objects.create(
            title='Регистр',
            type=Task.Type.TEXT,
            answer_mode=Task.AnswerMode.SHORT,
            correct_answer='Hello',
        )
        self.assertTrue(task.is_short_answer_correct('hello'))
        task.case_sensitive = True
        self.assertFalse(task.is_short_answer_correct('hello'))
        self.assertTrue(task.is_short_answer_correct('Hello'))

    def test_gap_answers_are_case_insensitive(self):
        task = Task.objects.create(
            title='Пропуски',
            type=Task.Type.GAP,
            body='Заполните пропуски.',
        )
        TaskBlock.objects.create(
            task=task, kind=TaskBlock.Kind.GAP, answers='4\nчетыре', order=0,
        )
        TaskBlock.objects.create(
            task=task, kind=TaskBlock.Kind.GAP, answers='Москва', order=1,
        )
        self.assertEqual(task.gap_numbers, [1, 2])
        self.assertTrue(task.is_gap_answer_correct(1, ' четыре '))
        self.assertTrue(task.is_gap_answer_correct(2, 'москва'))
        self.assertFalse(task.is_gap_answer_correct(2, 'Петербург'))
        self.assertFalse(task.is_gap_answer_correct(3, 'что-то'))

    def test_deleting_user_removes_their_tasks(self):
        Task.objects.create(title='Задача', author=self.teacher)
        self.teacher.delete()
        self.assertFalse(Task.objects.exists())


class LessonModelTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.task_a = Task.objects.create(title='Задача A', author=self.teacher)
        self.task_b = Task.objects.create(title='Задача B', author=self.teacher)

    def test_lesson_task_order(self):
        lesson = Lesson.objects.create(title='Урок 1', author=self.teacher)
        LessonTask.objects.create(lesson=lesson, task=self.task_b, order=2)
        LessonTask.objects.create(lesson=lesson, task=self.task_a, order=1)
        self.assertEqual(lesson.tasks_ordered, [self.task_a, self.task_b])

    def test_unique_task_in_lesson(self):
        lesson = Lesson.objects.create(title='Урок 1', author=self.teacher)
        LessonTask.objects.create(lesson=lesson, task=self.task_a, order=1)
        with self.assertRaises(Exception):
            LessonTask.objects.create(lesson=lesson, task=self.task_a, order=2)


class LessonViewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.bank = TaskBank.objects.create(
            name='Информатика ЕГЭ', author=self.teacher,
        )
        self.topic = Topic.objects.create(
            bank=self.bank, name='Тема 1', order=1,
        )
        self.task = Task.objects.create(
            title='Задача 1', author=self.teacher, task_number='1_1',
            bank=self.bank, topic=self.topic,
        )
        self.lesson = Lesson.objects.create(title='Урок 1', author=self.teacher)

    def test_lesson_list_requires_teacher(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('lesson_list'))
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('home'))

    def test_create_lesson(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('lesson_create'), {
            'title': 'Новый урок',
            'description': 'Описание',
        })
        self.assertRedirects(response, reverse('lesson_detail', args=[Lesson.objects.latest('id').pk]))

    def test_add_and_remove_task(self):
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('lesson_quick_add_task', args=[self.lesson.pk, self.task.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        self.assertEqual(self.lesson.entries.count(), 1)
        self.client.post(
            reverse('lesson_remove_task', args=[self.lesson.pk, self.task.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        self.assertEqual(self.lesson.entries.count(), 0)

    def test_lesson_detail_has_topic_select(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('lesson_detail', args=[self.lesson.pk]))
        self.assertContains(response, 'id="id_bank"')
        self.assertContains(response, 'id="id_topic"')
        self.assertContains(response, 'id="lesson-task-list"')
        self.assertContains(
            response, f'action="{reverse("lesson_detail", args=[self.lesson.pk])}"',
        )

    def test_lesson_detail_shows_tasks_for_topic(self):
        task2 = Task.objects.create(
            title='Задача 2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic, body='Условие второй задачи',
        )
        topic2 = Topic.objects.create(bank=self.bank, name='Тема 2', order=2)
        other_task = Task.objects.create(
            title='Другая тема', author=self.teacher, task_number='2_1',
            bank=self.bank, topic=topic2, body='Условие другой темы',
        )
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_detail', args=[self.lesson.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        self.assertContains(response, 'Условие второй задачи')
        self.assertNotContains(response, 'Условие другой темы')
        self.assertContains(
            response,
            reverse('lesson_quick_add_task', args=[self.lesson.pk, task2.pk]),
        )
        self.assertContains(response, 'class="task-actions"')
        self.assertContains(response, 'task-add-form')
        self.assertContains(response, 'task-remove-form')
        self.assertContains(
            response,
            reverse('lesson_quick_add_task', args=[self.lesson.pk, task2.pk]),
        )
        self.assertNotContains(
            response,
            reverse('lesson_quick_add_task', args=[self.lesson.pk, other_task.pk]),
        )

    def test_lesson_detail_sorts_tasks_naturally(self):
        task10 = Task.objects.create(
            title='Задача 10', author=self.teacher, task_number='1_10',
            bank=self.bank, topic=self.topic, body='Задача 10',
        )
        task2 = Task.objects.create(
            title='Задача 2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic, body='Задача 2',
        )
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_detail', args=[self.lesson.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        content = response.content.decode()
        self.assertLess(
            content.index(
                reverse('lesson_quick_add_task', args=[self.lesson.pk, task2.pk]),
            ),
            content.index(
                reverse('lesson_quick_add_task', args=[self.lesson.pk, task10.pk]),
            ),
        )

    def test_lesson_detail_marks_tasks_in_lesson(self):
        task2 = Task.objects.create(
            title='Задача 2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic, body='Условие второй задачи',
        )
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_detail', args=[self.lesson.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        self.assertContains(response, 'Добавлена в урок')
        self.assertContains(
            response,
            reverse('lesson_remove_task', args=[self.lesson.pk, self.task.pk]),
        )
        self.assertContains(
            response,
            reverse('lesson_quick_add_task', args=[self.lesson.pk, task2.pk]),
        )

    def test_lesson_remove_task_redirects_with_filters(self):
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_remove_task', args=[self.lesson.pk, self.task.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        expected = (
            reverse('lesson_detail', args=[self.lesson.pk])
            + f'?bank={self.bank.pk}&topic={self.topic.pk}'
        )
        self.assertRedirects(response, expected)
        self.assertFalse(self.lesson.entries.filter(task=self.task).exists())

    def test_lesson_detail_topic_only_own_tasks(self):
        other = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.TEACHER,
        )
        other_bank = TaskBank.objects.create(name='Чужая база', author=other)
        other_topic = Topic.objects.create(bank=other_bank, name='Чужая тема')
        other_task = Task.objects.create(
            title='Чужая', author=other, task_number='1_1',
            bank=other_bank, topic=other_topic, body='Чужое условие',
        )
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_detail', args=[self.lesson.pk]),
            {'bank': other_bank.pk, 'topic': other_topic.pk},
        )
        self.assertNotContains(response, 'Чужое условие')
        self.assertNotContains(
            response,
            reverse('lesson_quick_add_task', args=[self.lesson.pk, other_task.pk]),
        )

    def test_quick_add_task_adds_with_next_order(self):
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=3)
        task2 = Task.objects.create(
            title='Задача 2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic,
        )
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_quick_add_task', args=[self.lesson.pk, task2.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        expected = (
            reverse('lesson_detail', args=[self.lesson.pk])
            + f'?bank={self.bank.pk}&topic={self.topic.pk}'
        )
        self.assertRedirects(response, expected)
        entry = self.lesson.entries.get(task=task2)
        self.assertEqual(entry.order, 4)

    def test_quick_add_task_does_not_duplicate(self):
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('lesson_quick_add_task', args=[self.lesson.pk, self.task.pk]),
        )
        self.assertEqual(self.lesson.entries.count(), 1)

    def test_quick_add_task_returns_json_for_ajax(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_quick_add_task', args=[self.lesson.pk, self.task.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['lesson_task_ids'], [self.task.pk])
        self.assertEqual(data['entries'][0]['task_id'], self.task.pk)
        self.assertEqual(data['entries'][0]['order'], 1)
        self.assertTrue(self.lesson.entries.filter(task=self.task).exists())

    def test_remove_task_returns_json_for_ajax(self):
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_remove_task', args=[self.lesson.pk, self.task.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['lesson_task_ids'], [])
        self.assertFalse(self.lesson.entries.filter(task=self.task).exists())

    def test_add_all_related_returns_json_for_ajax(self):
        other = Task.objects.create(
            title='1_2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic,
        )
        self.task.related_tasks.add(other)
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_quick_add_related_tasks', args=[self.lesson.pk, other.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(
            set(data['lesson_task_ids']), {self.task.pk, other.pk},
        )

    def test_quick_add_task_rejects_foreign_task(self):
        other = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.TEACHER,
        )
        other_task = Task.objects.create(
            title='Чужая', author=other, task_number='1_1',
        )
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_quick_add_task', args=[self.lesson.pk, other_task.pk]),
        )
        self.assertEqual(response.status_code, 404)

    def test_add_all_related_tasks(self):
        other = Task.objects.create(
            title='1_2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic,
        )
        self.task.related_tasks.add(other)
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('lesson_quick_add_related_tasks', args=[self.lesson.pk, other.pk]),
        )
        self.assertRedirects(response, reverse('lesson_detail', args=[self.lesson.pk]))
        self.assertEqual(
            set(self.lesson.entries.values_list('task_id', flat=True)),
            {self.task.pk, other.pk},
        )

    def test_lesson_detail_shows_add_all_related_button(self):
        other = Task.objects.create(
            title='1_2', author=self.teacher, task_number='1_2',
            bank=self.bank, topic=self.topic,
        )
        self.task.related_tasks.add(other)
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_detail', args=[self.lesson.pk]),
            {'bank': self.bank.pk, 'topic': self.topic.pk},
        )
        self.assertContains(response, 'Добавить все связанные задачи')


class CourseViewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.client.force_login(self.teacher)

    def test_course_ids_restart_after_deleting_last_course(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        self.client.post(reverse('course_delete', args=[course.pk]))
        new_course = Course.objects.create(title='Новый курс', author=self.teacher)
        self.assertEqual(new_course.pk, 1)

    def test_module_and_lesson_ids_restart_after_deleting_last_course(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        module = CourseModule.objects.create(course=course, title='Модуль')
        Lesson.objects.create(title='Урок', author=self.teacher, module=module)
        self.client.post(reverse('course_delete', args=[course.pk]))
        new_course = Course.objects.create(title='Новый курс', author=self.teacher)
        new_module = CourseModule.objects.create(course=new_course, title='Модуль')
        new_lesson = Lesson.objects.create(
            title='Урок', author=self.teacher, module=new_module,
        )
        self.assertEqual(new_module.pk, 1)
        self.assertEqual(new_lesson.pk, 1)

    def test_course_list_orders_oldest_first(self):
        old = Course.objects.create(title='Старый курс', author=self.teacher)
        new = Course.objects.create(title='Новый курс', author=self.teacher)
        response = self.client.get(reverse('course_list'))
        self.assertEqual(list(response.context['courses']), [old, new])

    def test_course_detail_has_delete_button(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        response = self.client.get(reverse('course_detail', args=[course.pk]))
        self.assertContains(
            response,
            f'action="{reverse("course_delete", args=[course.pk])}"',
        )

    def test_course_form_has_exam_mode(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        response = self.client.get(reverse('course_edit', args=[course.pk]))
        self.assertContains(response, 'Режим экзамена')

    def test_deleting_user_removes_courses_and_lessons(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        lesson = Lesson.objects.create(title='Урок', author=self.teacher)
        self.teacher.delete()
        self.assertFalse(Course.objects.filter(pk=course.pk).exists())
        self.assertFalse(Lesson.objects.filter(pk=lesson.pk).exists())


class LessonExamTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.course = Course.objects.create(
            title='probniki ЕГЭ', author=self.teacher, exam_mode=True,
        )
        self.module = CourseModule.objects.create(
            course=self.course, title='Модуль',
        )
        self.lesson = Lesson.objects.create(
            title='Пробник 1', author=self.teacher, module=self.module,
        )
        self.text_task = Task.objects.create(
            title='Краткий', type=Task.Type.TEXT, author=self.teacher,
            answer_mode=Task.AnswerMode.SHORT, correct_answer='42', points=2,
        )
        self.gap_task = Task.objects.create(
            title='Пропуски', type=Task.Type.GAP, author=self.teacher, points=2,
        )
        TaskBlock.objects.create(
            task=self.gap_task, kind=TaskBlock.Kind.GAP, answers='4', order=0,
        )
        LessonTask.objects.create(lesson=self.lesson, task=self.text_task, order=1)
        LessonTask.objects.create(lesson=self.lesson, task=self.gap_task, order=2)
        self.client.force_login(self.student)

    def test_exam_requires_exam_mode(self):
        self.course.exam_mode = False
        self.course.save(update_fields=['exam_mode'])
        response = self.client.get(reverse('lesson_exam', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 404)

    def test_exam_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('lesson_exam', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 302)

    def test_student_opens_exam(self):
        response = self.client.get(reverse('lesson_exam', args=[self.lesson.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Краткий')
        self.assertContains(response, 'Задание 1')
        self.assertContains(response, 'Дано ответов')
        self.assertContains(response, '0/2')

    def test_exam_saves_text_answer(self):
        response = self.client.post(
            reverse('lesson_exam', args=[self.lesson.pk]) + '?task=1',
            {'task_id': self.text_task.pk, 'answer_text': '42'},
        )
        self.assertRedirects(
            response,
            f'{reverse("lesson_exam", args=[self.lesson.pk])}?task=1&saved=1',
        )
        submission = Submission.objects.get(
            lesson=self.lesson, task=self.text_task,
        )
        self.assertIsNone(submission.assignment)
        self.assertEqual(submission.student, self.student)
        self.assertEqual(submission.status, Submission.Status.CORRECT)
        self.assertEqual(submission.score, Decimal('2.00'))

    def test_exam_saves_gap_answer(self):
        self.client.post(
            reverse('lesson_exam', args=[self.lesson.pk]) + '?task=2',
            {'task_id': self.gap_task.pk, 'gap_1': '4'},
        )
        submission = Submission.objects.get(
            lesson=self.lesson, task=self.gap_task,
        )
        self.assertEqual(submission.gap_answers, {'1': '4'})
        self.assertEqual(submission.status, Submission.Status.CORRECT)
        self.assertEqual(submission.score, Decimal('2.00'))

    def test_exam_counts_answered_and_shows_result(self):
        self.client.post(
            reverse('lesson_exam', args=[self.lesson.pk]) + '?task=1',
            {'task_id': self.text_task.pk, 'answer_text': '42'},
        )
        response = self.client.get(reverse('lesson_exam', args=[self.lesson.pk]))
        self.assertContains(response, '1/2')
        result = self.client.get(
            reverse('lesson_exam_result', args=[self.lesson.pk]),
        )
        self.assertContains(result, '1/2')
        self.assertContains(result, '2 из 4')

    def test_author_can_preview_exam_without_exam_mode(self):
        self.course.exam_mode = False
        self.course.save(update_fields=['exam_mode'])
        self.client.force_login(self.teacher)
        response = self.client.get(
            reverse('lesson_exam', args=[self.lesson.pk]) + '?preview=1',
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Просмотр как ученик')

    def test_preview_does_not_save_answers(self):
        self.client.force_login(self.teacher)
        self.client.post(
            reverse('lesson_exam', args=[self.lesson.pk]) + '?preview=1',
            {'task_id': self.text_task.pk, 'answer_text': '42'},
        )
        self.assertFalse(Submission.objects.filter(lesson=self.lesson).exists())

    def test_lesson_detail_has_student_view_button(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('lesson_detail', args=[self.lesson.pk]))
        self.assertContains(response, 'Как ученик')


class TaskCrudViewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.topic = Topic.objects.create(bank=self.bank, name='Логика', order=1)
        self.client.force_login(self.teacher)

    def _formset_data(self, prefix, rows):
        data = {
            f'{prefix}-TOTAL_FORMS': str(len(rows)),
            f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
        }
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f'{prefix}-{i}-{key}'] = value
        return data

    def _base_data(self):
        data = {
            'bank': str(self.bank.pk),
            'topic': str(self.topic.pk),
        }
        data.update(self._formset_data('blocks', []))
        return data

    def test_create_choice_task(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'choice',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', [
            {'text': '8', 'is_correct': 'on', 'order': '1'},
            {'text': '16', 'is_correct': '', 'order': '2'},
        ]))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.answer_options.filter(is_correct=True).count(), 1)
        self.assertEqual(task.type, Task.Type.TEXT)

    def test_create_programming_task(self):
        data = {
            'type': 'programming',
            'difficulty': 'medium',
            'time_limit_ms': '2000',
            'memory_limit_mb': '128',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', [
            {'input_data': '1 2\n', 'expected_output': '3\n', 'is_public': 'on', 'order': '1'},
        ]))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.test_cases.count(), 1)
        self.assertEqual(task.type, Task.Type.PROGRAMMING)

    def test_create_short_answer_task(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.correct_answer, '8')

    def _short_answer_data(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        return data

    def test_create_task_defaults_to_one_point(self):
        response = self.client.post(reverse('task_create'), self._short_answer_data())
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.points, 1)

    def test_create_task_with_custom_points(self):
        data = self._short_answer_data()
        data['points'] = '3'
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.points, 3)
        detail = self.client.get(task.get_absolute_url())
        self.assertContains(detail, 'Баллы: 3')

    def test_task_points_cannot_be_zero(self):
        data = self._short_answer_data()
        data['points'] = '0'
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(author=self.teacher).exists())

    def test_create_task_with_related_tasks(self):
        other = Task.objects.create(
            title='1_9', author=self.teacher, task_number='1_9',
            bank=self.bank, topic=self.topic,
        )
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
            'body': 'Сколько будет?',
            'related_tasks': [other.pk],
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(list(task.related_tasks.all()), [other])
        self.assertEqual(list(other.related_tasks.all()), [task])
        detail = self.client.get(task.get_absolute_url())
        self.assertContains(detail, 'Связанные задачи')
        self.assertContains(detail, other.title)

    def test_task_form_shows_related_tasks_field(self):
        other = Task.objects.create(
            title='Связанная задача', author=self.teacher,
            bank=self.bank, topic=self.topic,
        )
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'Связанные задачи')
        self.assertContains(response, 'Не связана')
        self.assertContains(response, 'id="related-search"')
        self.assertContains(response, other.title)

    def test_empty_related_choice_is_ignored(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
            'body': 'Вопрос',
            'related_tasks': '',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertFalse(task.related_tasks.exists())

    def test_edit_form_preselects_related_tasks(self):
        first = Task.objects.create(
            title='A', author=self.teacher, bank=self.bank, topic=self.topic,
            task_number='1_1',
        )
        second = Task.objects.create(
            title='B', author=self.teacher, bank=self.bank, topic=self.topic,
            task_number='1_2',
        )
        first.related_tasks.add(second)
        response = self.client.get(reverse('task_edit', args=[first.pk]))
        self.assertIn(str(second.pk), response.context['form'].selected_related_ids)
        self.assertRegex(
            response.content.decode(),
            rf'<option value="{second.pk}"\s+selected>',
        )

    def test_symmetrize_related_tasks_repairs_one_sided_links(self):
        first = Task.objects.create(
            title='A', author=self.teacher, bank=self.bank, topic=self.topic,
        )
        second = Task.objects.create(
            title='B', author=self.teacher, bank=self.bank, topic=self.topic,
        )
        Task.related_tasks.through.objects.create(
            from_task_id=first.pk, to_task_id=second.pk,
        )
        self.assertFalse(second.related_tasks.exists())

        from django.apps import apps as global_apps

        module = importlib.import_module(
            'tasks.migrations.0022_symmetrize_related_tasks'
        )
        module.symmetrize_related_tasks(global_apps, None)

        self.assertEqual(list(second.related_tasks.all()), [first])
        self.assertEqual(list(first.related_tasks.all()), [second])

    def test_create_gap_task(self):
        data = {
            'type': 'gap',
            'difficulty': 'easy',
            'source': 'author',
            'body': 'Заполните пропуски.',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        data.update(self._formset_data('blocks', [
            {'kind': 'text', 'text': '2 + 2 = '},
            {'kind': 'gap', 'answers': '4\nчетыре'},
            {'kind': 'text', 'text': ', а 3 × 3 = '},
            {'kind': 'gap', 'answers': '9'},
        ]))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.type, Task.Type.GAP)
        self.assertEqual(task.blocks.count(), 4)
        self.assertEqual(task.gap_numbers, [1, 2])
        self.assertTrue(task.is_gap_answer_correct(1, 'Четыре'))
        self.assertTrue(task.is_gap_answer_correct(2, '9'))

    def test_task_form_has_gap_section(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'Задача с пропусками')
        self.assertContains(response, 'blocks-TOTAL_FORMS')
        self.assertContains(response, 'block-empty-form')
        self.assertContains(response, 'Добавить текст')
        self.assertContains(response, 'Добавить пропуск')
        self.assertContains(response, 'block-move-up')
        self.assertContains(response, 'block-move-down')

    def test_task_form_has_answer_rule_checkboxes(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'Регистр ответа должен совпадать')
        self.assertContains(response, 'Показывать верные и ошибочные ячейки')
        self.assertContains(response, 'Оценка зависит от числа верных ячеек')

    def test_create_task_with_answer_rules(self):
        data = self._short_answer_data()
        data.update({
            'case_sensitive': 'on',
            'show_cell_results': 'on',
            'score_by_cells': 'on',
        })
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertTrue(task.case_sensitive)
        self.assertTrue(task.show_cell_results)
        self.assertTrue(task.score_by_cells)

    def test_gap_blocks_respect_order_field(self):
        data = {
            'type': 'gap',
            'difficulty': 'easy',
            'source': 'author',
            'body': 'Заполните пропуски.',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        data.update(self._formset_data('blocks', [
            {'kind': 'text', 'text': 'Первый', 'order': '2'},
            {'kind': 'gap', 'answers': '1', 'order': '1'},
            {'kind': 'text', 'text': 'Третий', 'order': '0'},
        ]))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(
            list(task.blocks.values_list('kind', 'text', 'answers')),
            [
                ('text', 'Третий', ''),
                ('gap', '', '1'),
                ('text', 'Первый', ''),
            ],
        )

    def test_edit_gap_task_reorders_blocks(self):
        task = Task.objects.create(
            title='Пропуски', type=Task.Type.GAP, author=self.teacher,
            bank=self.bank, topic=self.topic, task_number='1_1',
        )
        first = TaskBlock.objects.create(
            task=task, kind=TaskBlock.Kind.TEXT, text='Первый', order=0,
        )
        second = TaskBlock.objects.create(
            task=task, kind=TaskBlock.Kind.GAP, answers='1', order=1,
        )
        data = {
            'type': 'gap',
            'difficulty': 'easy',
            'source': 'author',
            'body': 'Заполните пропуски.',
            'bank': str(self.bank.pk),
            'topic': str(self.topic.pk),
            'blocks-TOTAL_FORMS': '2',
            'blocks-INITIAL_FORMS': '2',
            'blocks-MIN_NUM_FORMS': '0',
            'blocks-MAX_NUM_FORMS': '1000',
            'blocks-0-id': str(first.pk),
            'blocks-0-kind': 'gap',
            'blocks-0-answers': '9',
            'blocks-0-order': '1',
            'blocks-1-id': str(second.pk),
            'blocks-1-kind': 'text',
            'blocks-1-text': 'Второй текст',
            'blocks-1-order': '0',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_edit', args=[task.pk]), data)
        task.refresh_from_db()
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(
            list(task.blocks.values_list('kind', 'text', 'answers')),
            [
                ('text', 'Второй текст', ''),
                ('gap', '', '9'),
            ],
        )

    def test_gap_task_requires_gap_block(self):
        data = {
            'type': 'gap',
            'difficulty': 'easy',
            'source': 'author',
            'body': 'Заполните пропуски.',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        data.update(self._formset_data('blocks', [
            {'kind': 'text', 'text': 'Только текст без пропуска'},
        ]))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(type=Task.Type.GAP, author=self.teacher).exists())

    def test_programming_task_requires_case(self):
        data = {
            'type': 'programming',
            'difficulty': 'easy',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(type=Task.Type.PROGRAMMING, author=self.teacher).exists())

    def test_choice_task_requires_correct_option(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'choice',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', [
            {'text': '8', 'is_correct': '', 'order': '1'},
        ]))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(type=Task.Type.TEXT, answer_mode=Task.AnswerMode.CHOICE, author=self.teacher).exists())

    def test_edit_task(self):
        task = Task.objects.create(
            title='Старое название', type=Task.Type.TEXT, author=self.teacher,
        )
        data = {
            'type': 'text',
            'difficulty': 'hard',
            'answer_mode': 'short',
            'correct_answer': '42',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_edit', args=[task.pk]), data)
        task.refresh_from_db()
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.difficulty, Task.Difficulty.HARD)

    def test_create_requires_topic(self):
        data = {
            'bank': str(self.bank.pk),
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        data.update(self._formset_data('blocks', []))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(author=self.teacher).exists())

    def test_first_task_number_starts_at_one(self):
        data = {
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
            'source': 'author',
        }
        data.update(self._base_data())
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.task_number, '1_1')


    def test_delete_task(self):
        task = Task.objects.create(title='Удаляемая', author=self.teacher)
        response = self.client.post(reverse('task_delete', args=[task.pk]))
        self.assertRedirects(response, reverse('task_list'))
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

    def test_ids_restart_after_deleting_last_task(self):
        task = Task.objects.create(title='Удаляемая', author=self.teacher)
        self.client.post(reverse('task_delete', args=[task.pk]))
        new_task = Task.objects.create(title='Новая', author=self.teacher)
        self.assertEqual(new_task.pk, 1)

    def test_task_list_has_delete_button(self):
        task = Task.objects.create(title='Удаляемая', author=self.teacher)
        response = self.client.get(reverse('task_list'))
        self.assertContains(response, f'action="{reverse("task_delete", args=[task.pk])}"')

    def test_task_detail_url_includes_bank(self):
        task = Task.objects.create(
            title='В базе', author=self.teacher, bank=self.bank, topic=self.topic,
        )
        self.assertEqual(
            task.get_absolute_url(),
            reverse('bank_task_detail', args=[self.bank.pk, task.pk]),
        )
        response = self.client.get(task.get_absolute_url())
        self.assertEqual(response.status_code, 200)

    def test_legacy_task_url_redirects_to_bank_url(self):
        task = Task.objects.create(
            title='В базе', author=self.teacher, bank=self.bank,
        )
        response = self.client.get(reverse('task_detail', args=[task.pk]))
        self.assertRedirects(response, task.get_absolute_url())

    def test_task_detail_rejects_wrong_bank(self):
        task = Task.objects.create(
            title='В базе', author=self.teacher, bank=self.bank,
        )
        other_bank = TaskBank.objects.create(name='Другая', author=self.teacher)
        response = self.client.get(
            reverse('bank_task_detail', args=[other_bank.pk, task.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_task_without_bank_keeps_plain_url(self):
        task = Task.objects.create(title='Без базы', author=self.teacher)
        self.assertEqual(
            task.get_absolute_url(),
            reverse('task_detail', args=[task.pk]),
        )

    def test_crud_requires_teacher(self):
        self.client.force_login(self.student)
        for url_name in ('task_create', 'task_list'):
            response = self.client.get(reverse(url_name))
            self.assertRedirects(response, reverse('home'))


class TaskBankTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )

    def test_create_bank(self):
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('bank_create'), {
            'name': 'ОГЭ по информатике',
            'description': 'Для 9 класса',
        })
        bank = TaskBank.objects.get(name='ОГЭ по информатике')
        self.assertRedirects(response, reverse('bank_detail', args=[bank.pk]))
        self.assertEqual(bank.author, self.teacher)

    def test_only_own_banks_in_list(self):
        TaskBank.objects.create(name='Моя база', author=self.teacher)
        TaskBank.objects.create(name='Чужая база', author=self.other_teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('bank_list'))
        self.assertContains(response, 'Моя база')
        self.assertNotContains(response, 'Чужая база')

    def test_bank_list_orders_oldest_first(self):
        old = TaskBank.objects.create(name='Старая база', author=self.teacher)
        new = TaskBank.objects.create(name='Новая база', author=self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('bank_list'))
        self.assertEqual(list(response.context['banks']), [old, new])

    def test_edit_bank(self):
        bank = TaskBank.objects.create(name='База', author=self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('bank_edit', args=[bank.pk]), {
            'name': 'Новое имя',
            'description': 'Описание',
        })
        self.assertRedirects(response, reverse('bank_detail', args=[bank.pk]))
        bank.refresh_from_db()
        self.assertEqual(bank.name, 'Новое имя')

    def test_delete_bank(self):
        bank = TaskBank.objects.create(name='База', author=self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.post(reverse('bank_delete', args=[bank.pk]))
        self.assertRedirects(response, reverse('bank_list'))
        self.assertFalse(TaskBank.objects.filter(pk=bank.pk).exists())

    def test_bank_ids_restart_after_deleting_last_bank(self):
        bank = TaskBank.objects.create(name='База', author=self.teacher)
        self.client.force_login(self.teacher)
        self.client.post(reverse('bank_delete', args=[bank.pk]))
        new_bank = TaskBank.objects.create(name='Новая база', author=self.teacher)
        self.assertEqual(new_bank.pk, 1)

    def test_deleting_bank_removes_tasks_and_resets_sequences(self):
        bank = TaskBank.objects.create(name='База', author=self.teacher)
        topic = Topic.objects.create(bank=bank, name='Тема', order=1)
        task = Task.objects.create(
            title='Задача', author=self.teacher, bank=bank, topic=topic,
        )
        self.client.force_login(self.teacher)
        self.client.post(reverse('bank_delete', args=[bank.pk]))
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())
        self.assertFalse(Topic.objects.filter(pk=topic.pk).exists())
        new_bank = TaskBank.objects.create(name='Новая база', author=self.teacher)
        new_topic = Topic.objects.create(bank=new_bank, name='Новая тема', order=1)
        new_task = Task.objects.create(
            title='Новая задача', author=self.teacher,
            bank=new_bank, topic=new_topic,
        )
        self.assertEqual(new_bank.pk, 1)
        self.assertEqual(new_topic.pk, 1)
        self.assertEqual(new_task.pk, 1)

    def test_cannot_access_other_teachers_bank(self):
        bank = TaskBank.objects.create(name='Чужая база', author=self.other_teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('bank_detail', args=[bank.pk]))
        self.assertEqual(response.status_code, 404)

    def test_bank_list_requires_teacher(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('bank_list'))
        self.assertRedirects(response, reverse('home'))

    def test_save_task_into_bank(self):
        bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        topic = Topic.objects.create(bank=bank, name='Логика', order=1)
        self.client.force_login(self.teacher)
        form = TaskForm(user=self.teacher)
        self.assertEqual(set(form.fields['bank'].queryset), {bank})
        response = self.client.post(
            reverse('task_create'),
            {
                'bank': str(bank.pk),
                'topic': str(topic.pk),
                'type': 'text',
                'difficulty': 'easy',
                'answer_mode': 'short',
                'correct_answer': '42',
                'source': 'author',
                'options-TOTAL_FORMS': '0',
                'options-INITIAL_FORMS': '0',
                'options-MIN_NUM_FORMS': '0',
                'options-MAX_NUM_FORMS': '1000',
                'cases-TOTAL_FORMS': '0',
                'cases-INITIAL_FORMS': '0',
                'cases-MIN_NUM_FORMS': '0',
                'cases-MAX_NUM_FORMS': '1000',
                'blocks-TOTAL_FORMS': '0',
                'blocks-INITIAL_FORMS': '0',
                'blocks-MIN_NUM_FORMS': '0',
                'blocks-MAX_NUM_FORMS': '1000',
            },
        )
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.bank, bank)

    def test_bank_name_preselect(self):
        bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.client.force_login(self.teacher)
        form = TaskForm(user=self.teacher, initial={'bank': bank.pk})
        self.assertEqual(form['bank'].value(), bank.pk)

    def test_bank_queryset_limited_to_ege_and_oge(self):
        ege = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        oge = TaskBank.objects.create(name='Информатика ОГЭ', author=self.teacher)
        TaskBank.objects.create(name='Другая база', author=self.teacher)
        form = TaskForm(user=self.teacher)
        self.assertEqual(list(form.fields['bank'].queryset), [ege, oge])


    def test_task_list_filter_by_bank(self):
        bank = TaskBank.objects.create(name='Моя база', author=self.teacher)
        Task.objects.create(title='В базе', author=self.teacher, bank=bank)
        Task.objects.create(title='Вне базы', author=self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('task_list'), {'bank': bank.pk})
        self.assertContains(response, 'В базе')
        self.assertNotContains(response, 'Вне базы')


class TaskTopicTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.TEACHER,
        )
        self.bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.client.force_login(self.teacher)

    def test_create_topic(self):
        response = self.client.post(reverse('topic_create', args=[self.bank.pk]), {
            'name': 'Системы счисления',
        })
        self.assertRedirects(response, reverse('bank_detail', args=[self.bank.pk]))
        topic = Topic.objects.get(bank=self.bank, name='Системы счисления')
        self.assertEqual(topic.bank, self.bank)
        self.assertEqual(topic.order, 1)

    def test_new_topic_order_increments(self):
        Topic.objects.create(bank=self.bank, name='Логика', order=1)
        self.client.post(reverse('topic_create', args=[self.bank.pk]), {
            'name': 'Алгоритмы',
        })
        topic = Topic.objects.get(bank=self.bank, name='Алгоритмы')
        self.assertEqual(topic.order, 2)


    def test_duplicate_topic_name_rejected(self):
        Topic.objects.create(bank=self.bank, name='Логика')
        self.client.post(reverse('topic_create', args=[self.bank.pk]), {
            'name': 'логика',
        })
        self.assertEqual(Topic.objects.filter(bank=self.bank).count(), 1)
        # тема с тем же названием (без учёта регистра) не добавлена

    def test_delete_topic_keeps_tasks(self):
        topic = Topic.objects.create(bank=self.bank, name='Логика')
        task = Task.objects.create(title='Задача 1', author=self.teacher,
                                   bank=self.bank, topic=topic)
        self.client.post(reverse('topic_delete', args=[topic.pk]))
        self.assertFalse(Topic.objects.filter(pk=topic.pk).exists())
        task.refresh_from_db()
        self.assertIsNone(task.topic)

    def test_bank_detail_deletes_topic_via_post(self):
        topic = Topic.objects.create(bank=self.bank, name='Логика')
        response = self.client.get(reverse('bank_detail', args=[self.bank.pk]))
        delete_url = reverse('topic_delete', args=[topic.pk])
        self.assertContains(response, f'action="{delete_url}"')
        self.assertNotContains(response, f'href="{delete_url}"')

    def test_cannot_create_topic_in_other_bank(self):
        other_bank = TaskBank.objects.create(name='Чужое', author=self.other_teacher)
        response = self.client.post(reverse('topic_create', args=[other_bank.pk]), {
            'name': 'Тема',
        })
        self.assertEqual(response.status_code, 404)

    def test_bank_detail_links_to_task_inside_bank(self):
        task = Task.objects.create(
            title='Задача в базе', author=self.teacher, bank=self.bank,
        )
        response = self.client.get(reverse('bank_detail', args=[self.bank.pk]))
        self.assertContains(response, f'href="{task.get_absolute_url()}"')

    def test_bank_detail_groups_tasks_by_topic(self):
        topic = Topic.objects.create(bank=self.bank, name='Логика')
        Topic.objects.create(bank=self.bank, name='Кодирование')
        Task.objects.create(title='Задача в теме', author=self.teacher,
                            bank=self.bank, topic=topic)
        Task.objects.create(title='Задача без темы', author=self.teacher,
                            bank=self.bank)
        response = self.client.get(reverse('bank_detail', args=[self.bank.pk]))
        self.assertContains(response, 'Логика')
        self.assertContains(response, 'Кодирование')
        self.assertContains(response, 'Задача в теме')
        self.assertContains(response, 'Задача без темы')

    def test_save_task_with_topic(self):
        topic = Topic.objects.create(bank=self.bank, name='Логика', order=1)
        self.client.post(reverse('task_create'), {
            'bank': str(self.bank.pk),
            'topic': str(topic.pk),
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '42',
            'source': 'author',
            'options-TOTAL_FORMS': '0',
            'options-INITIAL_FORMS': '0',
            'options-MIN_NUM_FORMS': '0',
            'options-MAX_NUM_FORMS': '1000',
            'cases-TOTAL_FORMS': '0',
            'cases-INITIAL_FORMS': '0',
            'cases-MIN_NUM_FORMS': '0',
            'cases-MAX_NUM_FORMS': '1000',
            'blocks-TOTAL_FORMS': '0',
            'blocks-INITIAL_FORMS': '0',
            'blocks-MIN_NUM_FORMS': '0',
            'blocks-MAX_NUM_FORMS': '1000',
        })
        task = Task.objects.latest('pk')
        self.assertEqual(task.topic, topic)
        self.assertEqual(task.task_number, '1_1')

    def test_task_number_sequence_per_topic(self):
        topic = Topic.objects.create(bank=self.bank, name='Логика', order=1)
        Task.objects.create(
            title='1_1', author=self.teacher, bank=self.bank, topic=topic,
            task_number='1_1',
        )
        response = self.client.post(reverse('task_create'), {
            'bank': str(self.bank.pk),
            'topic': str(topic.pk),
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '42',
            'source': 'author',
            'options-TOTAL_FORMS': '0',
            'options-INITIAL_FORMS': '0',
            'options-MIN_NUM_FORMS': '0',
            'options-MAX_NUM_FORMS': '1000',
            'cases-TOTAL_FORMS': '0',
            'cases-INITIAL_FORMS': '0',
            'cases-MIN_NUM_FORMS': '0',
            'cases-MAX_NUM_FORMS': '1000',
            'blocks-TOTAL_FORMS': '0',
            'blocks-INITIAL_FORMS': '0',
            'blocks-MIN_NUM_FORMS': '0',
            'blocks-MAX_NUM_FORMS': '1000',
        })
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        self.assertEqual(task.task_number, '1_2')


    def test_topic_queryset_limited_to_bank(self):
        topic_in_bank = Topic.objects.create(bank=self.bank, name='В моей базе')
        other_bank = TaskBank.objects.create(name='Другая', author=self.teacher)
        topic_in_other = Topic.objects.create(bank=other_bank, name='В другой базе')
        form = TaskForm(user=self.teacher, data={
            'bank': str(self.bank.pk),
            'type': 'text',
            'difficulty': 'easy',
            'source': 'author',
        })
        self.assertIn(topic_in_bank, form.fields['topic'].queryset)
        self.assertNotIn(topic_in_other, form.fields['topic'].queryset)

    def test_task_detail_includes_katex(self):
        task = Task.objects.create(
            title='Формулы', author=self.teacher, bank=self.bank,
            body='Сумма $a+b$',
        )
        response = self.client.get(task.get_absolute_url())
        self.assertContains(response, 'katex.min.css')
        self.assertContains(response, 'js-math')
        self.assertContains(response, '$a+b$')

    def test_task_form_has_math_preview(self):
        response = self.client.get(reverse('task_create'))
        self.assertContains(response, 'katex.min.css')
        self.assertContains(response, 'body-preview')
        self.assertContains(response, 'renderMathInElement')


class TaskAttachmentTests(DjangoTestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.topic = Topic.objects.create(bank=self.bank, name='Логика', order=1)
        self.client.force_login(self.teacher)

    def _task_data(self):
        return {
            'bank': str(self.bank.pk),
            'topic': str(self.topic.pk),
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '42',
            'source': 'author',
            'options-TOTAL_FORMS': '0',
            'options-INITIAL_FORMS': '0',
            'options-MIN_NUM_FORMS': '0',
            'options-MAX_NUM_FORMS': '1000',
            'cases-TOTAL_FORMS': '0',
            'cases-INITIAL_FORMS': '0',
            'cases-MIN_NUM_FORMS': '0',
            'cases-MAX_NUM_FORMS': '1000',
            'blocks-TOTAL_FORMS': '0',
            'blocks-INITIAL_FORMS': '0',
            'blocks-MIN_NUM_FORMS': '0',
            'blocks-MAX_NUM_FORMS': '1000',
        }

    def _upload(self, name='data.txt', content=b'hello'):
        return SimpleUploadedFile(name, content, content_type='text/plain')

    def test_create_task_with_attachment(self):
        response = self.client.post(
            reverse('task_create'),
            {**self._task_data(), 'attachments': self._upload()},
        )
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        attachment = task.attachments.get()
        self.assertEqual(attachment.filename, 'data.txt')
        detail = self.client.get(task.get_absolute_url())
        self.assertContains(detail, 'data.txt')
        self.assertContains(detail, attachment.file.url)

    def test_rejects_disallowed_extension(self):
        response = self.client.post(
            reverse('task_create'),
            {
                **self._task_data(),
                'attachments': SimpleUploadedFile(
                    'data.pdf', b'pdf', content_type='application/pdf'
                ),
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'недопустимый формат')
        self.assertFalse(Task.objects.filter(author=self.teacher).exists())

    def test_edit_removes_selected_attachment(self):
        task = Task.objects.create(title='1_1', author=self.teacher)
        attachment = TaskAttachment.objects.create(
            task=task, file=self._upload(), original_name='data.txt',
        )
        path = attachment.file.path
        response = self.client.post(
            reverse('task_edit', args=[task.pk]),
            {**self._task_data(), 'remove_attachments': [attachment.pk]},
        )
        task.refresh_from_db()
        self.assertRedirects(response, task.get_absolute_url())
        self.assertFalse(TaskAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertFalse(os.path.exists(path))

    def test_delete_task_removes_attachment_file(self):
        task = Task.objects.create(title='1_1', author=self.teacher)
        attachment = TaskAttachment.objects.create(
            task=task, file=self._upload(), original_name='data.txt',
        )
        path = attachment.file.path
        response = self.client.post(reverse('task_delete', args=[task.pk]))
        self.assertRedirects(response, reverse('task_list'))
        self.assertFalse(os.path.exists(path))


class TaskImageTests(DjangoTestCase):
    @classmethod
    def setUpClass(cls):
        cls._media_root = tempfile.mkdtemp()
        cls._override = override_settings(MEDIA_ROOT=cls._media_root)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        shutil.rmtree(cls._media_root, ignore_errors=True)

    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.other_teacher = User.objects.create_user(
            username='other', password='pass12345', role=User.Role.TEACHER,
        )
        self.bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.topic = Topic.objects.create(bank=self.bank, name='Логика', order=1)

    def _image(self, name='tiny.png'):
        buffer = BytesIO()
        PILImage.new('RGB', (4, 4), 'white').save(buffer, format='PNG')
        return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

    def _formset_data(self, prefix, rows):
        data = {
            f'{prefix}-TOTAL_FORMS': str(len(rows)),
            f'{prefix}-INITIAL_FORMS': '0',
            f'{prefix}-MIN_NUM_FORMS': '0',
            f'{prefix}-MAX_NUM_FORMS': '1000',
        }
        for i, row in enumerate(rows):
            for key, value in row.items():
                data[f'{prefix}-{i}-{key}'] = value
        return data

    def _task_data(self, body):
        data = {
            'bank': str(self.bank.pk),
            'topic': str(self.topic.pk),
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '42',
            'source': 'author',
            'body': body,
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        data.update(self._formset_data('blocks', []))
        return data

    def test_upload_requires_teacher(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('task_image_upload'), {'image': self._image()},
        )
        self.assertRedirects(response, reverse('home'))
        self.assertEqual(TaskImage.objects.count(), 0)

    def test_upload_creates_image(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('task_image_upload'), {'image': self._image()},
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        image = TaskImage.objects.get(token=payload['token'])
        self.assertEqual(image.author, self.teacher)
        self.assertIsNone(image.task)
        self.assertTrue(payload['url'].startswith('/media/'))

    def test_upload_rejects_non_image(self):
        self.client.force_login(self.teacher)
        upload = SimpleUploadedFile('notes.txt', b'hello', content_type='text/plain')
        response = self.client.post(reverse('task_image_upload'), {'image': upload})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(TaskImage.objects.count(), 0)

    def test_create_task_links_inline_image(self):
        image = TaskImage.objects.create(author=self.teacher, image=self._image())
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('task_create'),
            self._task_data(f'Найдите ответ\n[[img:{image.token}]]\n'),
        )
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        image.refresh_from_db()
        self.assertEqual(image.task, task)
        detail = self.client.get(task.get_absolute_url())
        self.assertContains(detail, '<img')
        self.assertContains(detail, image.image.url)

    def test_edit_task_removes_unused_image(self):
        task = Task.objects.create(title='Условие', author=self.teacher)
        image = TaskImage.objects.create(
            task=task, author=self.teacher, image=self._image(),
        )
        file_path = image.image.path
        task.body = f'Старое условие [[img:{image.token}]]'
        task.save()
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('task_edit', args=[task.pk]),
            self._task_data('Новое условие без картинки'),
        )
        task.refresh_from_db()
        self.assertRedirects(response, task.get_absolute_url())
        self.assertFalse(TaskImage.objects.filter(pk=image.pk).exists())
        self.assertFalse(os.path.exists(file_path))

    def test_cannot_link_other_teachers_image(self):
        image = TaskImage.objects.create(
            author=self.other_teacher, image=self._image(),
        )
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('task_create'),
            self._task_data(f'Текст [[img:{image.token}]]'),
        )
        task = Task.objects.latest('pk')
        self.assertRedirects(response, task.get_absolute_url())
        image.refresh_from_db()
        self.assertIsNone(image.task)
        detail = self.client.get(task.get_absolute_url())
        self.assertNotContains(detail, image.image.url)


class BlockTextRenderingTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.bank = TaskBank.objects.create(name='Информатика ЕГЭ', author=self.teacher)
        self.topic = Topic.objects.create(bank=self.bank, name='Тема', order=1)
        self.client.force_login(self.teacher)

    def test_render_block_text_allows_line_breaks(self):
        from .templatetags.task_filters import render_block_text

        rendered = render_block_text('Первая<br>Вторая<BR/>Третья')
        self.assertIn('Первая<br>Вторая<br>Третья', rendered)

    def test_render_block_text_escapes_other_html(self):
        from .templatetags.task_filters import render_block_text

        rendered = render_block_text('<script>alert(1)</script>')
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)

    def test_task_detail_renders_gap_break(self):
        task = Task.objects.create(
            title='Пропуски', type=Task.Type.GAP, author=self.teacher,
            bank=self.bank, topic=self.topic,
        )
        TaskBlock.objects.create(
            task=task, kind=TaskBlock.Kind.TEXT,
            text='Строка 1<br>Строка 2',
        )
        response = self.client.get(task.get_absolute_url())
        self.assertContains(response, 'Строка 1<br>Строка 2')
        self.assertNotContains(response, '&lt;br&gt;')
