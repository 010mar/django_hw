from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import ParentLink
from assignments.models import Assignment, ClassGroup, Submission
from tasks.models import Task

from .heatmap import build_heatmap, level_for


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
        self.assertContains(response, 'задач решено всего')

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

    def test_progress_percent(self):
        self.make_submission(
            self.student, Submission.Status.OK, timezone.now(),
        )
        self.client.force_login(self.student)
        response = self.client.get(reverse('student_stats', args=[self.student.pk]))
        self.assertContains(response, '100%')


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


class HeatmapTests(TestCase):
    def test_shape(self):
        today = date.today()
        result = build_heatmap({})
        self.assertEqual(len(result['columns']), 53)
        self.assertEqual(len(result['rows']), 7)
        for week in result['columns']:
            self.assertEqual(len(week), 7)
        last_week = result['columns'][-1]
        self.assertTrue(last_week[-1]['in_future'])
        today_cells = [c for c in last_week if c['date'] == today]
        self.assertFalse(today_cells[0]['in_future'])

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
