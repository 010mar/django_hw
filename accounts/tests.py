import re
from urllib.parse import urlparse

from allauth.account.models import EmailAddress
from django.core import mail
from django.core.cache import cache
from django.test import Client, TestCase
from django.urls import reverse

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

    def test_signup_with_role_teacher(self):
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
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='petr@example.com')
        self.assertEqual(user.role, User.Role.TEACHER)

    def test_signup_form_has_role_field(self):
        response = Client().get(reverse('account_signup'))
        self.assertContains(response, 'Я регистрируюсь как')

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


class ParentLinkTests(TestCase):
    def test_parent_link(self):
        parent = User.objects.create_user(username='parent1', password='pass12345', role=User.Role.PARENT)
        child = User.objects.create_user(username='child1', password='pass12345', role=User.Role.STUDENT)
        ParentLink.objects.create(parent=parent, child=child)
        self.assertEqual(parent.children.count(), 1)
        self.assertEqual(child.parent_links.count(), 1)
