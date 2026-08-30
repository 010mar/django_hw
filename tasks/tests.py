from django.contrib.auth import get_user_model
from django.test import TestCase as DjangoTestCase
from django.urls import reverse

from .forms import AddTaskForm, TaskForm
from .models import AnswerOption, Lesson, LessonTask, Task, TaskBank
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
            title='Что выведет print(2**3)?',
            type=Task.Type.TEXT,
            answer_mode=Task.AnswerMode.SHORT,
            correct_answer='8',
        )
        self.assertTrue(task.is_short_answer_correct('8'))
        self.assertTrue(task.is_short_answer_correct(' 8 '))
        self.assertFalse(task.is_short_answer_correct('7'))


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
        self.task = Task.objects.create(title='Задача 1', author=self.teacher)
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
        response = self.client.post(
            reverse('lesson_add_task', args=[self.lesson.pk]),
            {'task': self.task.pk, 'order': 1},
        )
        self.assertRedirects(response, reverse('lesson_detail', args=[self.lesson.pk]))
        self.assertEqual(self.lesson.entries.count(), 1)
        self.client.post(reverse('lesson_remove_task', args=[self.lesson.pk, self.task.pk]))
        self.assertEqual(self.lesson.entries.count(), 0)

    def test_add_task_form_excludes_existing(self):
        self.task2 = Task.objects.create(title='Задача 2', author=self.teacher)
        LessonTask.objects.create(lesson=self.lesson, task=self.task, order=1)
        form = AddTaskForm(lesson=self.lesson)
        queryset = form.fields['task'].queryset
        self.assertFalse(queryset.filter(pk=self.task.pk).exists())
        self.assertIn(self.task2, queryset)


class TaskCrudViewTests(DjangoTestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
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

    def test_create_choice_task(self):
        data = {
            'title': 'Какой бит?',
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'choice',
        }
        data.update(self._formset_data('options', [
            {'text': '8', 'is_correct': 'on', 'order': '1'},
            {'text': '16', 'is_correct': '', 'order': '2'},
        ]))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.get(title='Какой бит?')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        self.assertEqual(task.answer_options.filter(is_correct=True).count(), 1)

    def test_create_programming_task(self):
        data = {
            'title': 'A+B',
            'type': 'programming',
            'difficulty': 'medium',
            'time_limit_ms': '2000',
            'memory_limit_mb': '128',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', [
            {'input_data': '1 2\n', 'expected_output': '3\n', 'is_public': 'on', 'order': '1'},
        ]))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.get(title='A+B')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        self.assertEqual(task.test_cases.count(), 1)

    def test_create_short_answer_task(self):
        data = {
            'title': 'Сколько бит?',
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'short',
            'correct_answer': '8',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        task = Task.objects.get(title='Сколько бит?')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))

    def test_programming_task_requires_case(self):
        data = {
            'title': 'Пусто',
            'type': 'programming',
            'difficulty': 'easy',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title='Пусто').exists())

    def test_choice_task_requires_correct_option(self):
        data = {
            'title': 'Без правильного',
            'type': 'text',
            'difficulty': 'easy',
            'answer_mode': 'choice',
        }
        data.update(self._formset_data('options', [
            {'text': '8', 'is_correct': '', 'order': '1'},
        ]))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Task.objects.filter(title='Без правильного').exists())

    def test_edit_task(self):
        task = Task.objects.create(
            title='Старое название', type=Task.Type.TEXT, author=self.teacher,
        )
        data = {
            'title': 'Новое название',
            'type': 'text',
            'difficulty': 'hard',
            'answer_mode': 'short',
            'correct_answer': '42',
        }
        data.update(self._formset_data('options', []))
        data.update(self._formset_data('cases', []))
        response = self.client.post(reverse('task_edit', args=[task.pk]), data)
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        task.refresh_from_db()
        self.assertEqual(task.title, 'Новое название')
        self.assertEqual(task.difficulty, Task.Difficulty.HARD)

    def test_delete_task(self):
        task = Task.objects.create(title='Удаляемая', author=self.teacher)
        response = self.client.post(reverse('task_delete', args=[task.pk]))
        self.assertRedirects(response, reverse('task_list'))
        self.assertFalse(Task.objects.filter(pk=task.pk).exists())

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
        bank = TaskBank.objects.create(name='Моя база', author=self.teacher)
        self.client.force_login(self.teacher)
        form = TaskForm(user=self.teacher)
        self.assertEqual(set(form.fields['bank'].queryset), {bank})
        response = self.client.post(
            reverse('task_create'),
            {
                'bank': str(bank.pk),
                'title': 'Задача из базы',
                'type': 'text',
                'difficulty': 'easy',
                'answer_mode': 'short',
                'correct_answer': '42',
                'options-TOTAL_FORMS': '0',
                'options-INITIAL_FORMS': '0',
                'options-MIN_NUM_FORMS': '0',
                'options-MAX_NUM_FORMS': '1000',
                'cases-TOTAL_FORMS': '0',
                'cases-INITIAL_FORMS': '0',
                'cases-MIN_NUM_FORMS': '0',
                'cases-MAX_NUM_FORMS': '1000',
            },
        )
        task = Task.objects.get(title='Задача из базы')
        self.assertRedirects(response, reverse('task_detail', args=[task.pk]))
        self.assertEqual(task.bank, bank)

    def test_bank_name_preselect(self):
        bank = TaskBank.objects.create(name='Моя база', author=self.teacher)
        self.client.force_login(self.teacher)
        form = TaskForm(user=self.teacher, initial={'bank': bank.pk})
        self.assertEqual(form['bank'].value(), bank.pk)

    def test_task_list_filter_by_bank(self):
        bank = TaskBank.objects.create(name='Моя база', author=self.teacher)
        in_bank = Task.objects.create(title='В базе', author=self.teacher, bank=bank)
        Task.objects.create(title='Вне базы', author=self.teacher)
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('task_list'), {'bank': bank.pk})
        self.assertContains(response, 'В базе')
        self.assertNotContains(response, 'Вне базы')
