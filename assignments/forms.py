from django import forms

from tasks.models import Lesson, Task

from .models import Assignment, ClassGroup


class ClassForm(forms.ModelForm):
    class Meta:
        model = ClassGroup
        fields = ('title',)
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
        }


class AssignmentForm(forms.ModelForm):
    lesson = forms.ModelChoiceField(
        queryset=Lesson.objects.none(),
        required=False,
        label='Урок (добавит его задачи)',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    deadline = forms.DateTimeField(
        required=False,
        label='Дедлайн (ГГГГ-ММ-ДД ЧЧ:ММ)',
        input_formats=['%Y-%m-%dT%H:%M'],
        widget=forms.DateTimeInput(
            attrs={'class': 'form-control', 'type': 'datetime-local'},
            format='%Y-%m-%dT%H:%M',
        ),
    )

    class Meta:
        model = Assignment
        fields = ('title', 'description', 'class_group', 'students', 'tasks', 'deadline')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'class_group': forms.Select(attrs={'class': 'form-select'}),
            'students': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 8}),
            'tasks': forms.SelectMultiple(attrs={'class': 'form-select', 'size': 10}),
        }

    def __init__(self, *args, author=None, **kwargs):
        super().__init__(*args, **kwargs)
        if author:
            self.fields['lesson'].queryset = Lesson.objects.filter(author=author)
            self.fields['class_group'].queryset = ClassGroup.objects.filter(teacher=author)
            self.fields['students'].queryset = self.fields['students'].queryset.filter(role='student')
            self.fields['class_group'].required = False
            self.fields['students'].required = False
            self.fields['tasks'].queryset = Task.objects.all()

    def clean(self):
        cleaned = super().clean()
        class_group = cleaned.get('class_group')
        students = cleaned.get('students')
        if not class_group and not students:
            self.add_error('class_group', 'Назначьте задание классу или конкретным ученикам.')
        tasks = cleaned.get('tasks')
        lesson = cleaned.get('lesson')
        if not tasks and not lesson:
            self.add_error('tasks', 'Добавьте задачи или укажите урок.')
        return cleaned
