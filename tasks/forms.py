from django import forms

from .models import AnswerOption, Lesson, Task, TestCase


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = (
            'title',
            'body',
            'type',
            'difficulty',
            'image',
            'answer_mode',
            'correct_answer',
            'language',
            'time_limit_ms',
            'memory_limit_mb',
        )
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'answer_mode': forms.Select(attrs={'class': 'form-select'}),
            'correct_answer': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'time_limit_ms': forms.NumberInput(attrs={'class': 'form-control'}),
            'memory_limit_mb': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('language', 'time_limit_ms', 'memory_limit_mb', 'answer_mode'):
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        task_type = cleaned.get('type')
        answer_mode = cleaned.get('answer_mode')
        correct_answer = cleaned.get('correct_answer', '')
        if task_type == Task.Type.TEXT and answer_mode == Task.AnswerMode.SHORT and not correct_answer.strip():
            self.add_error('correct_answer', 'Укажите правильный ответ для краткого ответа.')
        if task_type == Task.Type.PROGRAMMING:
            if not cleaned.get('time_limit_ms'):
                cleaned['time_limit_ms'] = 1000
            if not cleaned.get('memory_limit_mb'):
                cleaned['memory_limit_mb'] = 128
        return cleaned


class AnswerOptionFormSet(forms.modelformset_factory(
    AnswerOption,
    fields=('text', 'is_correct', 'order'),
    extra=3,
    can_delete=True,
)):
    pass


class TestCaseFormSet(forms.modelformset_factory(
    TestCase,
    fields=('input_data', 'expected_output', 'is_public', 'order'),
    extra=2,
    can_delete=True,
)):
    pass


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ('title', 'description')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class AddTaskForm(forms.Form):
    task = forms.ModelChoiceField(
        queryset=Task.objects.none(),
        label='Задача',
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    order = forms.IntegerField(
        min_value=0,
        initial=0,
        label='Порядок',
        widget=forms.NumberInput(attrs={'class': 'form-control'}),
    )

    def __init__(self, *args, lesson=None, **kwargs):
        super().__init__(*args, **kwargs)
        if lesson:
            taken_ids = lesson.entries.values_list('task_id', flat=True)
            self.fields['task'].queryset = Task.objects.exclude(id__in=taken_ids)
