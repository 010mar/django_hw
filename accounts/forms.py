from allauth.account.forms import SignupForm
from django import forms

from .models import User

BOOTSTRAP_INPUT_CLASSES = {
    'email': 'form-control',
    'username': 'form-control',
    'password1': 'form-control',
    'password2': 'form-control',
}


class CustomSignupForm(SignupForm):
    role = forms.ChoiceField(
        choices=User.Role.choices,
        label='Я регистрируюсь как',
        initial=User.Role.STUDENT,
        widget=forms.RadioSelect(),
    )
    field_order = ['email', 'username', 'password1', 'password2', 'role']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name, cls in BOOTSTRAP_INPUT_CLASSES.items():
            field = self.fields.get(name)
            if field:
                field.widget.attrs.setdefault('class', cls)

    def save(self, request):
        user = super().save(request)
        user.role = self.cleaned_data['role']
        user.save(update_fields=['role'])
        return user    
    
    
    