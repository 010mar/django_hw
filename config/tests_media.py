import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import ParentLink
from assignments.models import Assignment, ClassGroup, Submission
from tasks.models import (
    Course,
    CourseModule,
    Lesson,
    LessonTask,
    Task,
    TaskAttachment,
    TaskImage,
)

User = get_user_model()


class ProtectedMediaTestCase(TestCase):
    def setUp(self):
        self.media_dir = tempfile.TemporaryDirectory()
        self.override = override_settings(
            MEDIA_ROOT=self.media_dir.name,
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'],
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media_dir.cleanup)

        self.teacher = User.objects.create_user(
            username='teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.other_teacher = User.objects.create_user(
            username='other-teacher', password='pass12345', role=User.Role.TEACHER,
        )
        self.student = User.objects.create_user(
            username='student', password='pass12345', role=User.Role.STUDENT,
        )
        self.other_student = User.objects.create_user(
            username='other-student', password='pass12345', role=User.Role.STUDENT,
        )
        self.parent = User.objects.create_user(
            username='parent', password='pass12345', role=User.Role.PARENT,
        )
        self.staff = User.objects.create_user(
            username='staff', password='pass12345', role=User.Role.TEACHER,
            is_staff=True,
        )

    def _write(self, rel_path, data=b'media'):
        path = Path(self.media_dir.name) / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _get(self, url, user):
        client = self.client_class()
        if user is not None:
            client.force_login(user)
        response = client.get(url)
        response.close()
        return response


class AvatarMediaTests(ProtectedMediaTestCase):
    def test_anonymous_is_redirected_to_login(self):
        self._write('avatars/me.png')
        response = self._get('/media/avatars/me.png', None)
        self.assertEqual(response.status_code, 302)

    def test_authenticated_user_can_load_avatar(self):
        self._write('avatars/me.png')
        self.student.avatar = 'avatars/me.png'
        self.student.save()
        response = self._get(self.student.avatar_url, self.other_student)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'private, max-age=0, must-revalidate')

    def test_missing_file_returns_404(self):
        self.student.avatar = 'avatars/missing.png'
        response = self._get(self.student.avatar_url, self.student)
        self.assertEqual(response.status_code, 404)


class SubmissionMediaTests(ProtectedMediaTestCase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(author=self.teacher, title='Задача')
        self.assignment = Assignment.objects.create(
            author=self.teacher, title='Домашка',
        )
        self.assignment.students.add(self.student)
        self.submission = Submission.objects.create(
            assignment=self.assignment,
            task=self.task,
            student=self.student,
            image='submissions/answer.png',
        )
        self._write('submissions/answer.png')

    def test_student_owner_can_view(self):
        response = self._get(self.submission.image_url, self.student)
        self.assertEqual(response.status_code, 200)

    def test_other_student_gets_404(self):
        response = self._get(self.submission.image_url, self.other_student)
        self.assertEqual(response.status_code, 404)

    def test_assignment_author_can_view(self):
        response = self._get(self.submission.image_url, self.teacher)
        self.assertEqual(response.status_code, 200)

    def test_unrelated_teacher_gets_404(self):
        response = self._get(self.submission.image_url, self.other_teacher)
        self.assertEqual(response.status_code, 404)

    def test_linked_parent_can_view(self):
        ParentLink.objects.create(parent=self.parent, child=self.student)
        response = self._get(self.submission.image_url, self.parent)
        self.assertEqual(response.status_code, 200)

    def test_unlinked_parent_gets_404(self):
        response = self._get(self.submission.image_url, self.parent)
        self.assertEqual(response.status_code, 404)

    def test_class_teacher_can_view(self):
        class_group = ClassGroup.objects.create(
            teacher=self.other_teacher, title='Класс',
        )
        class_group.students.add(self.student)
        self.assignment.class_group = class_group
        self.assignment.save()
        response = self._get(self.submission.image_url, self.other_teacher)
        self.assertEqual(response.status_code, 200)


class TaskMediaTests(ProtectedMediaTestCase):
    def setUp(self):
        super().setUp()
        self.task = Task.objects.create(
            author=self.teacher, title='Задача', image='tasks/task.png',
        )
        self._write('tasks/task.png')
        self.attachment = TaskAttachment.objects.create(
            task=self.task, file='tasks/files/doc.txt', original_name='doc.txt',
        )
        self._write('tasks/files/doc.txt')
        self.inline = TaskImage.objects.create(
            task=self.task, author=self.teacher, image='tasks/inline/1/x.png',
        )
        self._write('tasks/inline/1/x.png')

    def test_anonymous_is_redirected(self):
        response = self._get(self.task.image_url, None)
        self.assertEqual(response.status_code, 302)

    def test_author_can_view_all_task_media(self):
        for url in (self.task.image_url, self.attachment.file_url, self.inline.image_url):
            response = self._get(url, self.teacher)
            self.assertEqual(response.status_code, 200)

    def test_unrelated_teacher_gets_404(self):
        response = self._get(self.task.image_url, self.other_teacher)
        self.assertEqual(response.status_code, 404)

    def test_student_with_direct_assignment_can_view(self):
        assignment = Assignment.objects.create(
            author=self.teacher, title='Домашка',
        )
        assignment.students.add(self.student)
        assignment.tasks.add(self.task)
        for url in (self.task.image_url, self.attachment.file_url, self.inline.image_url):
            response = self._get(url, self.student)
            self.assertEqual(response.status_code, 200)

    def test_student_in_course_class_can_view(self):
        course = Course.objects.create(title='Курс', author=self.teacher)
        module = CourseModule.objects.create(course=course, title='Модуль')
        lesson = Lesson.objects.create(module=module, title='Урок', author=self.teacher)
        LessonTask.objects.create(lesson=lesson, task=self.task)
        class_group = ClassGroup.objects.create(
            teacher=self.teacher, title='Класс', course=course,
        )
        class_group.students.add(self.student)
        response = self._get(self.task.image_url, self.student)
        self.assertEqual(response.status_code, 200)

    def test_unrelated_student_gets_404(self):
        response = self._get(self.task.image_url, self.other_student)
        self.assertEqual(response.status_code, 404)

    def test_staff_can_view_any_media(self):
        self._write('private/report.txt')
        response = self._get('/media/private/report.txt', self.staff)
        self.assertEqual(response.status_code, 200)
        response = self._get('/media/private/report.txt', self.student)
        self.assertEqual(response.status_code, 404)

    def test_path_traversal_is_blocked(self):
        response = self._get('/media/../manage.py', self.staff)
        self.assertEqual(response.status_code, 404)


class MediaUrlPropertyTests(ProtectedMediaTestCase):
    def test_properties_return_empty_without_file(self):
        task = Task.objects.create(author=self.teacher, title='Без картинки')
        submission = Submission.objects.create(
            task=task, student=self.student,
        )
        self.assertEqual(self.student.avatar_url, '')
        self.assertEqual(task.image_url, '')
        self.assertEqual(submission.image_url, '')

    def test_properties_point_to_protected_view(self):
        task = Task.objects.create(
            author=self.teacher, title='Задача', image='tasks/t.png',
        )
        self.assertEqual(
            task.image_url,
            reverse('protected_media', args=['tasks/t.png']),
        )
