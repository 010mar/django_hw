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
        User.objects.create_user(
            username='petr', email='petr@example.com', password='pass12345'
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


class ParentLinkTests(TestCase):
    def test_parent_link(self):
        parent = User.objects.create_user(username='parent1', password='pass12345', role=User.Role.PARENT)
        child = User.objects.create_user(username='child1', password='pass12345', role=User.Role.STUDENT)
        ParentLink.objects.create(parent=parent, child=child)
        self.assertEqual(parent.children.count(), 1)
        self.assertEqual(child.parent_links.count(), 1)
