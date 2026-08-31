from django import forms

from .models import AnswerOption, Lesson, Task, TaskBank, TestCase, Topic


class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = (
            'bank',
            'topic',
            'source',
            'type',
            'difficulty',
            'body',
            'image',
            'answer_mode',
            'correct_answer',
            'language',
            'time_limit_ms',
            'memory_limit_mb',
        )
        widgets = {
            'bank': forms.Select(attrs={'class': 'form-select'}),
            'topic': forms.Select(attrs={'class': 'form-select'}),
            'source': forms.Select(attrs={'class': 'form-select'}),
            'type': forms.Select(attrs={'class': 'form-select'}),
            'difficulty': forms.Select(attrs={'class': 'form-select'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'answer_mode': forms.Select(attrs={'class': 'form-select'}),
            'correct_answer': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'time_limit_ms': forms.NumberInput(attrs={'class': 'form-control'}),
            'memory_limit_mb': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('language', 'time_limit_ms', 'memory_limit_mb', 'answer_mode'):
            self.fields[name].required = False
        self.fields['topic'].required = False
        if user is not None:
            self.fields['bank'].queryset = TaskBank.objects.filter(author=user)
        bank_id = None
        if self.data:
            bank_id = self.data.get('bank')
        elif self.instance and self.instance.bank_id:
            bank_id = self.instance.bank_id
        elif self.initial.get('bank'):
            bank_id = self.initial.get('bank')
        self.fields['topic'].queryset = (
            Topic.objects.filter(bank_id=bank_id) if bank_id else Topic.objects.none()
        )

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


class BaseTaskFormSet(forms.BaseModelFormSet):
    def clean(self):
        super().clean()
        idx = 0
        for form in self.forms:
            cd = form.cleaned_data
            if cd and not cd.get('DELETE') and not cd.get('order'):
                cd['order'] = idx
                idx += 1


class AnswerOptionForm(forms.ModelForm):
    class Meta:
        model = AnswerOption
        fields = ('text', 'is_correct', 'order')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['text'].required = False
        self.fields['order'].required = False
        self.fields['is_correct'].widget.attrs.setdefault('class', 'form-check-input')
        self.fields['text'].widget = forms.TextInput(attrs={'class': 'form-control'})
        self.fields['order'].widget = forms.NumberInput(attrs={'class': 'form-control'})


AnswerOptionFormSet = forms.modelformset_factory(
    AnswerOption,
    form=AnswerOptionForm,
    extra=3,
    can_delete=True,
    formset=BaseTaskFormSet,
)


class TestCaseForm(forms.ModelForm):
    class Meta:
        model = TestCase
        fields = ('input_data', 'expected_output', 'is_public', 'order')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['input_data'].required = False
        self.fields['expected_output'].required = False
        self.fields['order'].required = False
        self.fields['is_public'].widget.attrs.setdefault('class', 'form-check-input')
        self.fields['input_data'].widget = forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
        self.fields['expected_output'].widget = forms.Textarea(attrs={'class': 'form-control', 'rows': 2})
        self.fields['order'].widget = forms.NumberInput(attrs={'class': 'form-control'})


TestCaseFormSet = forms.modelformset_factory(
    TestCase,
    form=TestCaseForm,
    extra=2,
    can_delete=True,
    formset=BaseTaskFormSet,
)


class LessonForm(forms.ModelForm):
    class Meta:
        model = Lesson
        fields = ('title', 'description')
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class TaskBankForm(forms.ModelForm):
    class Meta:
        model = TaskBank
        fields = ('name', 'description')
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class TopicForm(forms.ModelForm):
    class Meta:
        model = Topic
        fields = ('name',)
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название темы',
            }),
        }

    def clean_name(self):
        return self.cleaned_data['name'].strip()


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

    def __init__(self, *args, lesson=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        tasks = Task.objects.all()
        if user is not None:
            tasks = tasks.filter(author=user)
        if lesson:
            taken_ids = lesson.entries.values_list('task_id', flat=True)
            tasks = tasks.exclude(id__in=taken_ids)
        self.fields['task'].queryset = tasks
