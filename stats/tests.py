from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import ParentLink
from assignments.models import Assignment, ClassGroup, Submission
from tasks.models import (
    Course,
    CourseModule,
    Lesson,
    LessonTask,
    Task,
    TaskBank,
    Topic,
)

from .heatmap import build_heatmap, level_for
from .services import (
    activity_streaks,
    solved_counts_by_day,
    task_results_chart,
)
from .templatetags.stats_tags import plural_ru


def create_user(username, role):
    return get_user_model().objects.create_user(
        username=username, password='pass12345', role=role,
    )


class StatsViewsBase(TestCase):
    def setUp(self):
        self.teacher = create_user('teacher', 'teacher')
        self.other_teacher = create_user('other_teacher', 'teacher')
        self.student = create_user('student', 'student')
        self.other_student = create_user('other_student', 'student')
        self.parent = create_user('parent', 'parent')
        self.task = Task.objects.create(title='Задача', author=self.teacher)
        self.assignment = Assignment.objects.create(
            title='ДЗ', author=self.teacher,
        )
        self.assignment.students.set([self.student])
        self.assignment.tasks.set([self.task])

    def make_submission(self, student, status, created_at):
        submission = Submission.objects.create(
            assignment=self.assignment, task=self.task,
            student=student, status=status,
        )
        Submission.objects.filter(pk=submission.pk).update(created_at=created_at)
        return submission


class MyStatsTests(StatsViewsBase):
    def test_student_sees_own_stats(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('my_stats'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Активность за последний год')
        self.assertContains(response, 'задача решена')

    def test_parent_redirected_from_my_stats(self):
        self.client.force_login(self.parent)
        response = self.client.get(reverse('my_stats'))
        self.assertRedirects(response, reverse('home'))

    def test_anonymous_redirected(self):
        response = self.client.get(reverse('my_stats'))
        self.assertRedirects(response, f'{reverse("account_login")}?next={reverse("my_stats")}')


class StudentStatsTests(StatsViewsBase):
    def test_student_sees_own_page(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)

    def test_student_cannot_see_other_student(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_stats', args=[self.other_student.pk]))
        self.assertEqual(response.status_code, 404)

    def test_parent_sees_child(self):
        ParentLink.objects.create(parent=self.parent, child=self.student)
        self.client.force_login(self.parent)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)

    def test_parent_cannot_see_unrelated_child(self):
        self.client.force_login(self.parent)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertEqual(response.status_code, 404)

    def test_teacher_sees_student(self):
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)

    def test_solved_counts_shown(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now() - timedelta(days=1),
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '1</div>')
        self.assertContains(response, 'Прогресс по заданиям')

    def test_activity_summary_shown(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now(),
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertContains(response, 'Активность за последний год')
        self.assertContains(response, 'Следующий день в 00:00 МСК')
        self.assertContains(response, 'heatmap-tooltip')
        self.assertContains(response, 'data-date=')
        self.assertContains(response, 'день без перерыва')
        self.assertContains(response, 'задача решена')

    def test_progress_percent(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now(),
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertContains(response, '100%')


class CourseFilterTests(StatsViewsBase):
    def setUp(self):
        super().setUp()
        self.course_a = Course.objects.create(
            title='infa ЕГЭ', author=self.teacher,
        )
        self.course_b = Course.objects.create(
            title='probniki ЕГЭ', author=self.teacher,
        )
        module = CourseModule.objects.create(
            course=self.course_a, title='Модуль', order=1,
        )
        self.lesson = Lesson.objects.create(
            module=module, title='Урок', author=self.teacher,
        )
        for title, course in (('9А', self.course_a), ('9Б', self.course_b)):
            class_group = ClassGroup.objects.create(
                title=title, teacher=self.teacher, course=course,
            )
            class_group.students.add(self.student)
        Submission.objects.create(
            lesson=self.lesson, task=self.task, student=self.student,
            status=Submission.Status.OK,
        )

    def test_course_selector_lists_student_courses(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('my_stats'))
        self.assertEqual(
            list(response.context['courses']),
            [self.course_a, self.course_b],
        )
        self.assertEqual(response.context['selected_course'], None)
        self.assertContains(response, 'infa ЕГЭ')
        self.assertContains(response, 'probniki ЕГЭ')

    def test_heatmap_counts_only_selected_course(self):
        self.client.force_login(self.student)
        response = self.client.get(
            f'{reverse("my_stats")}?course={self.course_a.pk}',
        )
        self.assertEqual(response.context['selected_course'], self.course_a)
        self.assertEqual(sum(response.context['stats']['heatmap'].values()), 1)
        self.assertEqual(response.context['stats']['solved_total'], 1)

        response = self.client.get(
            f'{reverse("my_stats")}?course={self.course_b.pk}',
        )
        self.assertEqual(response.context['selected_course'], self.course_b)
        self.assertEqual(sum(response.context['stats']['heatmap'].values()), 0)
        self.assertEqual(response.context['stats']['current_streak'], 0)
        self.assertEqual(response.context['stats']['solved_total'], 0)

    def test_unknown_course_falls_back_to_all(self):
        self.client.force_login(self.student)
        response = self.client.get(f'{reverse("my_stats")}?course=999')
        self.assertEqual(response.context['selected_course'], None)
        self.assertEqual(sum(response.context['stats']['heatmap'].values()), 1)

    def test_solved_counts_filter_by_course(self):
        self.assertEqual(
            sum(solved_counts_by_day(
                self.student, course=self.course_a,
            ).values()),
            1,
        )
        self.assertEqual(
            sum(solved_counts_by_day(
                self.student, course=self.course_b,
            ).values()),
            0,
        )


class TaskResultsChartTests(StatsViewsBase):
    def setUp(self):
        super().setUp()
        self.course = Course.objects.create(
            title='Курс', author=self.teacher,
        )
        module = CourseModule.objects.create(
            course=self.course, title='Модуль', order=1,
        )
        self.lesson = Lesson.objects.create(
            module=module, title='Урок', author=self.teacher,
        )
        bank = TaskBank.objects.create(name='Банк', author=self.teacher)
        self.topic_a = Topic.objects.create(
            bank=bank, name='Тема A', order=1,
        )
        self.topic_b = Topic.objects.create(
            bank=bank, name='Тема B', order=2,
        )
        self.task_a1 = Task.objects.create(
            title='A1', author=self.teacher, bank=bank,
            topic=self.topic_a, task_number='1',
        )
        self.task_a2 = Task.objects.create(
            title='A2', author=self.teacher, bank=bank,
            topic=self.topic_a, task_number='2',
        )
        self.task_b1 = Task.objects.create(
            title='B1', author=self.teacher, bank=bank,
            topic=self.topic_b, task_number='3',
        )
        for order, task in enumerate(
            (self.task_a1, self.task_a2, self.task_b1), start=1,
        ):
            LessonTask.objects.create(
                lesson=self.lesson, task=task, order=order,
            )
        class_group = ClassGroup.objects.create(
            title='9А', teacher=self.teacher, course=self.course,
        )
        class_group.students.add(self.student)
        for status in (Submission.Status.INCORRECT, Submission.Status.OK):
            Submission.objects.create(
                lesson=self.lesson, task=self.task_a1,
                student=self.student, status=status,
            )
        Submission.objects.create(
            lesson=self.lesson, task=self.task_b1,
            student=self.student, status=Submission.Status.WA,
        )

    def test_chart_labels_cover_topics_one_to_27(self):
        chart = task_results_chart(self.student, course=self.course)
        self.assertEqual(chart['labels'], list(range(1, 28)))
        self.assertEqual(len(chart['attempts']), len(chart['labels']))
        self.assertEqual(len(chart['solved']), len(chart['labels']))

    def test_counts_attempts_and_solved_by_topic(self):
        chart = task_results_chart(self.student, course=self.course)
        self.assertEqual(chart['attempts'][0], 2)
        self.assertEqual(chart['solved'][0], 1)
        self.assertEqual(chart['attempts'][1], 1)
        self.assertEqual(chart['solved'][1], 0)

    def test_page_renders_chart(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('my_stats'))
        self.assertEqual(response.context['task_chart']['labels'][0], 1)
        self.assertContains(response, 'Решённые задания по темам')
        self.assertContains(response, 'task-chart-data')


class ParentChildrenTests(StatsViewsBase):
    def test_parent_lists_children(self):
        ParentLink.objects.create(parent=self.parent, child=self.student)
        self.client.force_login(self.parent)
        response = self.client.get(reverse('parent_children'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'student')

    def test_student_redirected_from_children(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('parent_children'))
        self.assertRedirects(response, reverse('home'))


class ClassStatsTests(StatsViewsBase):
    def setUp(self):
        super().setUp()
        self.class_group = ClassGroup.objects.create(title='9Б', teacher=self.teacher)
        self.class_group.students.set([self.student, self.other_student])
        self.assignment.class_group = self.class_group
        self.assignment.save()

    def test_teacher_sees_class_stats(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now(),
        )
        self.client.force_login(self.teacher)
        response = self.client.get(reverse('class_stats', args=[self.class_group.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Средняя успеваемость')

    def test_other_teacher_cannot_see(self):
        self.client.force_login(self.other_teacher)
        response = self.client.get(reverse('class_stats', args=[self.class_group.pk]))
        self.assertEqual(response.status_code, 404)


class StreakTests(TestCase):
    def setUp(self):
        self.today = timezone.localdate()

    def test_empty_counts(self):
        result = activity_streaks({})
        self.assertEqual(result['current'], 0)
        self.assertEqual(result['longest'], 0)

    def test_consecutive_days(self):
        counts = {
            self.today: 2,
            self.today - timedelta(days=1): 1,
            self.today - timedelta(days=2): 3,
        }
        result = activity_streaks(counts)
        self.assertEqual(result['current'], 3)
        self.assertEqual(result['longest'], 3)

    def test_gap_splits_streaks(self):
        counts = {
            self.today: 1,
            self.today - timedelta(days=1): 1,
            self.today - timedelta(days=3): 1,
            self.today - timedelta(days=4): 1,
            self.today - timedelta(days=5): 1,
        }
        result = activity_streaks(counts)
        self.assertEqual(result['current'], 2)
        self.assertEqual(result['longest'], 3)

    def test_current_streak_survives_until_yesterday(self):
        counts = {
            self.today - timedelta(days=1): 1,
            self.today - timedelta(days=2): 1,
        }
        result = activity_streaks(counts)
        self.assertEqual(result['current'], 2)

    def test_stale_activity_resets_current_streak(self):
        counts = {self.today - timedelta(days=3): 1}
        result = activity_streaks(counts)
        self.assertEqual(result['current'], 0)
        self.assertEqual(result['longest'], 1)

    def test_zero_count_day_does_not_break_streak(self):
        counts = {
            self.today: 1,
            self.today - timedelta(days=1): 0,
            self.today - timedelta(days=2): 1,
        }
        result = activity_streaks(counts)
        self.assertEqual(result['current'], 1)
        self.assertEqual(result['longest'], 1)


class PluralRuTests(TestCase):
    def test_days(self):
        forms = 'день,дня,дней'
        self.assertEqual(plural_ru(1, forms), 'день')
        self.assertEqual(plural_ru(3, forms), 'дня')
        self.assertEqual(plural_ru(5, forms), 'дней')
        self.assertEqual(plural_ru(11, forms), 'дней')
        self.assertEqual(plural_ru(21, forms), 'день')
        self.assertEqual(plural_ru(24, forms), 'дня')

    def test_tasks(self):
        forms = 'задача решена,задачи решено,задач решено'
        self.assertEqual(plural_ru(1, forms), 'задача решена')
        self.assertEqual(plural_ru(2, forms), 'задачи решено')
        self.assertEqual(plural_ru(810, forms), 'задач решено')


class HeatmapTests(TestCase):
    def test_shape(self):
        today = date.today()
        result = build_heatmap({})
        self.assertEqual(len(result['columns']), 53)
        self.assertEqual(len(result['rows']), 7)
        for week in result['columns']:
            self.assertEqual(len(week), 7)
        last_week = result['columns'][-1]
        if today.weekday() < 6:
            self.assertTrue(last_week[-1]['in_future'])
        else:
            self.assertFalse(last_week[-1]['in_future'])
        today_cells = [c for c in last_week if c['date'] == today]
        self.assertTrue(today_cells)
        self.assertFalse(today_cells[0]['in_future'])
        self.assertEqual(result['today'], today)

    def test_month_labels_skip_partial_first_month(self):
        result = build_heatmap({}, today=date(2026, 11, 17))
        self.assertEqual(result['month_labels'][0]['index'], 2)
        self.assertEqual(result['month_labels'][0]['name'], 'дек.')
        self.assertEqual(result['month_labels'][-1]['name'], 'нояб.')

    def test_date_label(self):
        today = date(2026, 11, 17)
        result = build_heatmap({}, today=today)
        cells = [cell for week in result['columns'] for cell in week]
        cell = next(c for c in cells if c['date'] == today)
        self.assertEqual(cell['date_label'], '17 ноября 2026 г.')

    def test_levels(self):
        today = date.today()
        self.assertEqual(level_for(0), 0)
        self.assertEqual(level_for(1), 1)
        self.assertEqual(level_for(2), 1)
        self.assertEqual(level_for(3), 2)
        self.assertEqual(level_for(4), 2)
        self.assertEqual(level_for(5), 3)
        self.assertEqual(level_for(6), 3)
        self.assertEqual(level_for(9), 4)
        result = build_heatmap({today: 3})
        cells = [cell for week in result['columns'] for cell in week]
        today_cells = [c for c in cells if c['date'] == today]
        self.assertEqual(today_cells[0]['count'], 3)
        self.assertEqual(today_cells[0]['level'], 2)
