from allauth.account.forms import SignupForm
from django import forms
from django.utils.text import slugify
import random

from .models import User

BOOTSTRAP_INPUT_CLASSES = {
    'email': 'form-control',
    'first_name': 'form-control',
    'last_name': 'form-control',
    'password1': 'form-control',
    'password2': 'form-control',
}


class CustomSignupForm(SignupForm):
    first_name = forms.CharField(
        label='Имя',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    last_name = forms.CharField(
        label='Фамилия',
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
    )
    role = forms.ChoiceField(
        choices=User.Role.choices,
        label='Я регистрируюсь как',
        initial=User.Role.STUDENT,
        widget=forms.RadioSelect(),
    )
    field_order = ['email', 'first_name', 'last_name', 'password1', 'password2', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'username' in self.fields:
            del self.fields['username']
        for name, cls in BOOTSTRAP_INPUT_CLASSES.items():
            field = self.fields.get(name)
            if field:
                field.widget.attrs.setdefault('class', cls)

    def _generate_username(self):
        base = slugify(self.cleaned_data.get('first_name', '') + self.cleaned_data.get('last_name', ''))
        if not base:
            base = slugify(self.cleaned_data.get('email', '').split('@')[0])
        username = base
        while User.objects.filter(username=username).exists():
            username = f'{base}{random.randint(1000, 9999)}'
        return username

    def save(self, request):
        self.username = self._generate_username()
        user = super().save(request)
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.role = self.cleaned_data['role']
        user.save(update_fields=['first_name', 'last_name', 'role'])
        return user
