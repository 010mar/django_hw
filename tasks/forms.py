import re

from django import forms
from django.db.models import Case, When

from .models import (
    AnswerOption,
    Course,
    CourseModule,
    Lesson,
    Task,
    TaskBank,
    TaskBlock,
    TestCase,
    Topic,
)


class OptionalMultipleChoiceField(forms.ModelMultipleChoiceField):
    def clean(self, value):
        if value:
            if not isinstance(value, (list, tuple)):
                value = [value]
            value = [item for item in value if item not in ('', None)]
        return super().clean(value)


class TaskForm(forms.ModelForm):
    related_tasks = OptionalMultipleChoiceField(
        queryset=Task.objects.none(),
        required=False,
        label='Связанные задачи',
        help_text='Можно выбрать несколько задач, связанных с этой',
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': 6}),
    )

    class Meta:
        model = Task
        fields = (
            'bank',
            'topic',
            'related_tasks',
            'source',
            'type',
            'difficulty',
            'points',
            'case_sensitive',
            'show_cell_results',
            'score_by_cells',
            'body',
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
            'points': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
            'case_sensitive': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'show_cell_results': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'score_by_cells': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 5}),
            'answer_mode': forms.Select(attrs={'class': 'form-select'}),
            'correct_answer': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'time_limit_ms': forms.NumberInput(attrs={'class': 'form-control'}),
            'memory_limit_mb': forms.NumberInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ('language', 'time_limit_ms', 'memory_limit_mb', 'answer_mode', 'related_tasks'):
            self.fields[name].required = False
        self.fields['points'].required = False
        self.fields['topic'].required = True
        self.fields['topic'].empty_label = None
        if user is not None:
            self.fields['bank'].queryset = (
                TaskBank.objects.filter(
                    author=user,
                    name__in=['Информатика ЕГЭ', 'Информатика ОГЭ'],
                ).order_by(
                    Case(
                        When(name='Информатика ЕГЭ', then=0),
                        When(name='Информатика ОГЭ', then=1),
                    )
                )
            )
            self.fields['bank'].empty_label = None
            self.fields['bank'].required = True
        bank_id = None
        if self.data:
            bank_id = self.data.get('bank')
        elif self.instance and self.instance.bank_id:
            bank_id = self.instance.bank_id
        elif self.initial.get('bank'):
            bank_id = self.initial.get('bank')
        if bank_id and user is not None:
            self.fields['topic'].queryset = Topic.objects.filter(
                bank_id=bank_id, bank__author=user
            )
        elif bank_id:
            self.fields['topic'].queryset = Topic.objects.filter(bank_id=bank_id)
        else:
            self.fields['topic'].queryset = Topic.objects.none()
        if user is not None:
            related = (
                Task.objects
                .filter(author=user)
                .select_related('bank', 'topic')
                .order_by('task_number', 'pk')
            )
            if self.instance and self.instance.pk:
                related = related.exclude(pk=self.instance.pk)
            self.fields['related_tasks'].queryset = related

    @property
    def selected_related_ids(self):
        value = self['related_tasks'].value() or []
        return {str(getattr(item, 'pk', item)) for item in value}

    def clean_points(self):
        points = self.cleaned_data.get('points')
        if points is None:
            return 1
        if points < 1:
            raise forms.ValidationError('Баллы должны быть не меньше 1.')
        return points

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


class TaskBlockForm(forms.ModelForm):
    class Meta:
        model = TaskBlock
        fields = ('kind', 'text', 'answers', 'order')
        widgets = {
            'kind': forms.HiddenInput(),
            'order': forms.HiddenInput(),
            'text': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Текст задания',
            }),
            'answers': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'По одному ответу в строке',
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['kind'].required = False
        self.fields['text'].required = False
        self.fields['answers'].required = False
        self.fields['order'].required = False


class BaseTaskBlockFormSet(forms.BaseModelFormSet):
    def clean(self):
        super().clean()
        for form in self.forms:
            cleaned = getattr(form, 'cleaned_data', None)
            if not cleaned or cleaned.get('DELETE'):
                continue
            kind = cleaned.get('kind') or TaskBlock.Kind.TEXT
            if kind not in (TaskBlock.Kind.TEXT, TaskBlock.Kind.GAP):
                form.add_error('kind', 'Неизвестный тип блока.')
                continue
            if kind == TaskBlock.Kind.GAP and not (cleaned.get('answers') or '').strip():
                form.add_error('answers', 'Укажите хотя бы один правильный ответ.')


TaskBlockFormSet = forms.modelformset_factory(
    TaskBlock,
    form=TaskBlockForm,
    extra=0,
    can_delete=True,
    formset=BaseTaskBlockFormSet,
)


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ('title', 'description', 'exam_mode', 'flat_modules')
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название курса',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Описание курса',
            }),
            'exam_mode': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'flat_modules': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CourseModuleForm(forms.ModelForm):
    class Meta:
        model = CourseModule
        fields = ('title', 'description', 'start_date')
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Название модуля',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Дополнительное описание',
            }),
            'start_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
        }


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


def task_number_sort_key(number):
    return [
        (0, int(part)) if part.isdigit() else (1, part.lower())
        for part in re.split(r'(\d+)', number)
        if part
    ]
