import io
import re
import tempfile
from urllib.parse import urlparse

from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from .models import ParentLink, User


class AuthFlowTests(TestCase):
    def test_signup_with_role_student(self):
        response = Client().post(
            reverse('account_signup'),
            {
                'email': 'ivan@example.com',
                'first_name': 'Иван',
                'last_name': 'Иванов',
                'password1': 'supersecret99',
                'password2': 'supersecret99',
                'role': User.Role.STUDENT,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='ivan@example.com')
        self.assertEqual(user.role, User.Role.STUDENT)

    def test_signup_with_role_parent(self):
        response = Client().post(
            reverse('account_signup'),
            {
                'email': 'olga@example.com',
                'first_name': 'Ольга',
                'last_name': 'Орлова',
                'password1': 'supersecret99',
                'password2': 'supersecret99',
                'role': User.Role.PARENT,
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='olga@example.com')
        self.assertEqual(user.role, User.Role.PARENT)

    def test_signup_rejects_teacher_role(self):
        response = Client().post(
            reverse('account_signup'),
            {
                'email': 'petr@example.com',
                'first_name': 'Пётр',
                'last_name': 'Петров',
                'password1': 'supersecret99',
                'password2': 'supersecret99',
                'role': User.Role.TEACHER,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(email='petr@example.com').exists())

    def test_signup_form_has_role_field(self):
        response = Client().get(reverse('account_signup'))
        self.assertContains(response, 'Я регистрируюсь как')

    def test_signup_form_role_choices(self):
        response = Client().get(reverse('account_signup'))
        form = response.context['form']
        roles = {value for value, _label in form.fields['role'].choices}
        self.assertEqual(roles, {User.Role.STUDENT, User.Role.PARENT})

    def test_login_by_email(self):
        user = User.objects.create_user(
            username='petr', email='petr@example.com', password='pass12345'
        )
        EmailAddress.objects.create(
            user=user, email='petr@example.com', verified=True, primary=True
        )
        client = Client()
        response = client.post(
            reverse('account_login'),
            {'login': 'petr@example.com', 'password': 'pass12345'},
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['user'].is_authenticated)

    def test_home_requires_login(self):
        response = Client().get(reverse('home'))
        self.assertEqual(response.status_code, 302)

    def test_home_shows_role(self):
        user = User.objects.create_user(
            username='anna', email='anna@example.com', password='pass12345',
            role=User.Role.TEACHER,
        )
        client = Client()
        client.force_login(user)
        response = client.get(reverse('home'))
        self.assertContains(response, 'Учитель')


class EmailVerificationTests(TestCase):
    def setUp(self):
        cache.clear()

    def signup(self, email='new@example.com'):
        return self.client.post(
            reverse('account_signup'),
            {
                'email': email,
                'first_name': 'Новый',
                'last_name': 'Ученик',
                'password1': 'supersecret99',
                'password2': 'supersecret99',
                'role': User.Role.STUDENT,
            },
        )

    def confirmation_path(self):
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r'https?://\S+', mail.outbox[0].body)
        self.assertIsNotNone(match)
        return urlparse(match.group(0)).path

    def test_signup_sends_confirmation_email(self):
        response = self.signup('signup@example.com')
        self.assertRedirects(response, reverse('account_email_verification_sent'))
        user = User.objects.get(email='signup@example.com')
        address = EmailAddress.objects.get(user=user)
        self.assertFalse(address.verified)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertIn('Подтвердите адрес', mail.outbox[0].subject)
        self.assertIn('/accounts/confirm-email/', mail.outbox[0].body)

    def test_unverified_user_cannot_login(self):
        user = User.objects.create_user(
            username='unverified',
            email='unverified@example.com',
            password='pass12345',
        )
        EmailAddress.objects.create(
            user=user,
            email='unverified@example.com',
            verified=False,
            primary=True,
        )
        response = self.client.post(
            reverse('account_login'),
            {'login': 'unverified@example.com', 'password': 'pass12345'},
            follow=True,
        )
        self.assertFalse(response.context['user'].is_authenticated)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/confirm-email/', mail.outbox[0].body)

    def test_confirmation_link_verifies_email_and_logs_in(self):
        self.signup('confirm@example.com')
        path = self.confirmation_path()
        response = self.client.get(path)
        self.assertContains(response, 'Подтвердить')
        response = self.client.post(path)
        self.assertRedirects(response, reverse('home'))
        self.assertTrue(EmailAddress.objects.get(email='confirm@example.com').verified)
        self.assertIn('_auth_user_id', self.client.session)

    def test_duplicate_signup_does_not_create_second_account(self):
        self.signup('dup@example.com')
        response = self.signup('dup@example.com')
        self.assertRedirects(response, reverse('account_email_verification_sent'))
        self.assertEqual(User.objects.filter(email='dup@example.com').count(), 1)
        self.assertEqual(EmailAddress.objects.filter(email='dup@example.com').count(), 1)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_duplicate_signup_is_case_insensitive(self):
        self.signup('Case@example.com')
        self.signup('CASE@example.com')
        self.assertEqual(User.objects.filter(email='case@example.com').count(), 1)
        self.assertEqual(EmailAddress.objects.filter(email='case@example.com').count(), 1)


class ParentLinkTests(TestCase):
    def test_parent_link(self):
        parent = User.objects.create_user(username='parent1', password='pass12345', role=User.Role.PARENT)
        child = User.objects.create_user(username='child1', password='pass12345', role=User.Role.STUDENT)
        ParentLink.objects.create(parent=parent, child=child)
        self.assertEqual(parent.children.count(), 1)
        self.assertEqual(child.parent_links.count(), 1)


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='reset', email='reset@example.com', password='oldpass12345'
        )

    def request_reset(self, email='reset@example.com'):
        return self.client.post(reverse('account_reset_password'), {'email': email})

    def reset_path_from_email(self):
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r'https?://\S+', mail.outbox[0].body)
        self.assertIsNotNone(match)
        return urlparse(match.group(0)).path

    def test_reset_password_page_renders(self):
        response = self.client.get(reverse('account_reset_password'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Сброс пароля')
        self.assertContains(response, 'form-control')

    def test_reset_password_sends_email(self):
        response = self.request_reset()
        self.assertRedirects(response, reverse('account_reset_password_done'))
        self.assertIn('Сброс пароля', mail.outbox[0].subject)
        self.assertIn('/accounts/password/reset/key/', mail.outbox[0].body)

    def test_reset_password_sets_new_password(self):
        self.request_reset()
        response = self.client.get(self.reset_path_from_email())
        self.assertEqual(response.status_code, 302)
        path = response.url
        response = self.client.get(path)
        self.assertContains(response, 'Новый пароль')
        response = self.client.post(
            path, {'password1': 'newpass12345', 'password2': 'newpass12345'}
        )
        self.assertRedirects(response, reverse('account_reset_password_from_key_done'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('newpass12345'))

    def test_reset_password_unknown_email_sends_no_reset_link(self):
        response = self.request_reset(email='nobody@example.com')
        self.assertRedirects(response, reverse('account_reset_password_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertNotIn('/accounts/password/reset/key/', mail.outbox[0].body)

    def test_reset_password_bad_token_shows_message(self):
        response = self.client.get(
            reverse(
                'account_reset_password_from_key',
                kwargs={'uidb36': 'abc', 'key': 'bad'},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ссылка недействительна')


class ProfileTests(TestCase):
    def setUp(self):
        self.teacher = User.objects.create_user(
            username='teacher1', email='teacher1@example.com',
            password='pass12345', role=User.Role.TEACHER,
        )
        self.parent = User.objects.create_user(
            username='parent2', email='parent2@example.com',
            password='pass12345', role=User.Role.PARENT,
        )
        self.student = User.objects.create_user(
            username='student1', email='student1@example.com',
            password='pass12345', first_name='Гриша', last_name='Петров',
            role=User.Role.STUDENT,
        )

    def test_profile_requires_login(self):
        response = self.client.get(reverse('profile'))
        self.assertEqual(response.status_code, 302)

    def test_profile_updates_names(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('profile'),
            {'first_name': 'Григорий', 'last_name': 'Петров'},
        )
        self.assertRedirects(response, reverse('profile'))
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, 'Григорий')

    def test_profile_avatar_upload(self):
        buffer = io.BytesIO()
        Image.new('RGB', (1, 1), 'red').save(buffer, format='PNG')
        avatar = SimpleUploadedFile(
            'avatar.png', buffer.getvalue(), content_type='image/png'
        )
        self.client.force_login(self.student)
        with tempfile.TemporaryDirectory() as media_root, override_settings(
            MEDIA_ROOT=media_root
        ):
            response = self.client.post(
                reverse('profile'),
                {
                    'first_name': 'Гриша',
                    'last_name': 'Петров',
                    'avatar': avatar,
                },
            )
            self.assertRedirects(response, reverse('profile'))
            self.student.refresh_from_db()
            self.assertTrue(self.student.avatar)

    def test_profile_page_has_account_links(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, reverse('account_email'))
        self.assertContains(response, reverse('account_change_password'))

    def test_parent_can_link_and_unlink_child(self):
        self.client.force_login(self.parent)
        response = self.client.post(
            reverse('add_child'), {'email': 'student1@example.com'}
        )
        self.assertRedirects(response, reverse('profile'))
        link = ParentLink.objects.get(parent=self.parent, child=self.student)
        response = self.client.post(reverse('remove_child', args=[link.pk]))
        self.assertRedirects(response, reverse('profile'))
        self.assertFalse(ParentLink.objects.exists())

    def test_non_parent_cannot_link_child(self):
        self.client.force_login(self.teacher)
        response = self.client.post(
            reverse('add_child'), {'email': 'student1@example.com'}
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ParentLink.objects.exists())

    def test_parent_link_rejects_unknown_email(self):
        self.client.force_login(self.parent)
        response = self.client.post(
            reverse('add_child'), {'email': 'nobody@example.com'}, follow=True
        )
        self.assertContains(response, 'не найден')
        self.assertFalse(ParentLink.objects.exists())

    def test_profile_shows_children_for_parent(self):
        ParentLink.objects.create(parent=self.parent, child=self.student)
        self.client.force_login(self.parent)
        response = self.client.get(reverse('profile'))
        self.assertContains(response, 'Гриша Петров')
        self.assertContains(response, 'student1@example.com')

    def test_email_management_page_is_styled(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('account_email'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Адреса электронной почты')
        self.assertContains(response, 'form-control')

    def test_password_change_page_is_styled(self):
        self.client.force_login(self.student)
        response = self.client.get(reverse('account_change_password'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Смена пароля')
        self.assertContains(response, 'form-control')

    def test_password_change_updates_password(self):
        self.client.force_login(self.student)
        response = self.client.post(
            reverse('account_change_password'),
            {
                'oldpassword': 'pass12345',
                'password1': 'newpass12345',
                'password2': 'newpass12345',
            },
        )
        self.assertRedirects(response, reverse('account_change_password'))
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password('newpass12345'))
