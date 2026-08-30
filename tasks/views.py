from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required

from .forms import (
    AddTaskForm,
    AnswerOptionFormSet,
    LessonForm,
    TaskBankForm,
    TaskForm,
    TestCaseFormSet,
    TopicForm,
)
from .models import AnswerOption, Lesson, LessonTask, Task, TaskBank, TestCase, Topic


@teacher_required
def task_list(request):
    tasks = Task.objects.filter(author=request.user).select_related('author', 'bank', 'topic')
    bank_id = request.GET.get('bank')
    if bank_id:
        tasks = tasks.filter(bank_id=bank_id)
    banks = TaskBank.objects.filter(author=request.user)
    return render(request, 'tasks/task_list.html', {
        'tasks': tasks,
        'banks': banks,
        'current_bank': bank_id,
    })


@teacher_required
def bank_list(request):
    banks = TaskBank.objects.filter(author=request.user)
    return render(request, 'tasks/bank_list.html', {'banks': banks})


@teacher_required
def bank_create(request):
    form = TaskBankForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        bank = form.save(commit=False)
        bank.author = request.user
        bank.save()
        messages.success(request, 'База задач создана.')
        return redirect('bank_detail', pk=bank.pk)
    return render(request, 'tasks/bank_form.html', {'form': form, 'is_create': True})


@teacher_required
def bank_detail(request, pk):
    bank = get_object_or_404(TaskBank, pk=pk, author=request.user)
    tasks = bank.tasks.select_related('author').all()
    topics = bank.topics.all()
    untopiced = [t for t in tasks if not t.topic_id]
    return render(request, 'tasks/bank_detail.html', {
        'bank': bank,
        'topics': topics,
        'untopiced': untopiced,
        'topic_form': TopicForm(),
    })


@teacher_required
def topic_create(request, pk):
    bank = get_object_or_404(TaskBank, pk=pk, author=request.user)
    if request.method == 'POST':
        form = TopicForm(request.POST)
        if form.is_valid():
            name = form.cleaned_data['name']
            if any(t.name.strip().lower() == name.lower() for t in bank.topics.all()):
                messages.error(request, 'Тема с таким названием уже есть в этой базе.')
            else:
                topic = form.save(commit=False)
                topic.bank = bank
                topic.save()
                messages.success(request, 'Тема добавлена.')
    return redirect('bank_detail', pk=bank.pk)


@teacher_required
def topic_delete(request, pk):
    topic = get_object_or_404(Topic, pk=pk, bank__author=request.user)
    bank_id = topic.bank_id
    if request.method == 'POST':
        topic.delete()
        messages.success(request, 'Тема удалена.')
    return redirect('bank_detail', pk=bank_id)


@teacher_required
def bank_edit(request, pk):
    bank = get_object_or_404(TaskBank, pk=pk, author=request.user)
    form = TaskBankForm(request.POST or None, instance=bank)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'База задач обновлена.')
        return redirect('bank_detail', pk=bank.pk)
    return render(request, 'tasks/bank_form.html', {
        'form': form,
        'is_create': False,
        'bank': bank,
    })


@teacher_required
def bank_delete(request, pk):
    bank = get_object_or_404(TaskBank, pk=pk, author=request.user)
    if request.method == 'POST':
        bank.delete()
        messages.success(request, 'База задач удалена.')
    return redirect('bank_list')


def _save_formsets(task, option_formset, case_formset):
    for obj in option_formset.save(commit=False):
        if obj.text.strip():
            obj.task = task
            obj.save()
    for obj in option_formset.deleted_objects:
        obj.delete()
    for obj in case_formset.save(commit=False):
        if obj.expected_output.strip():
            obj.task = task
            obj.save()
    for obj in case_formset.deleted_objects:
        obj.delete()


def _validate_formsets(task, option_formset, case_formset):
    errors = []
    real_options = [
        d for d in option_formset.cleaned_data
        if d and not d.get('DELETE') and (d.get('text') or '').strip()
    ]
    real_cases = [
        d for d in case_formset.cleaned_data
        if d and not d.get('DELETE') and (d.get('expected_output') or '').strip()
    ]
    if task.type == Task.Type.PROGRAMMING and not real_cases:
        errors.append('Добавьте хотя бы один тест для задачи на программирование.')
    if task.type == Task.Type.TEXT and task.answer_mode == Task.AnswerMode.CHOICE:
        if not real_options:
            errors.append('Добавьте хотя бы один вариант ответа.')
        elif not any(d.get('is_correct') for d in real_options):
            errors.append('Отметьте хотя бы один правильный вариант.')
    return errors


@teacher_required
def task_create(request):
    initial_bank = request.GET.get('bank') or None
    if initial_bank and not TaskBank.objects.filter(
            pk=initial_bank, author=request.user).exists():
        initial_bank = None
    form = TaskForm(
        request.POST or None,
        request.FILES or None,
        user=request.user,
        initial={'bank': initial_bank} if initial_bank else None,
    )
    option_formset = AnswerOptionFormSet(
        request.POST or None,
        prefix='options',
        queryset=AnswerOption.objects.none(),
    )
    case_formset = TestCaseFormSet(
        request.POST or None,
        prefix='cases',
        queryset=TestCase.objects.none(),
    )
    if request.method == 'POST':
        if form.is_valid() and option_formset.is_valid() and case_formset.is_valid():
            task = form.save(commit=False)
            task.author = request.user
            formset_errors = _validate_formsets(task, option_formset, case_formset)
            if not formset_errors:
                task.save()
                _save_formsets(task, option_formset, case_formset)
                messages.success(request, 'Задача создана.')
                return redirect('task_detail', pk=task.pk)
            for error in formset_errors:
                messages.error(request, error)
    return render(request, 'tasks/task_form.html', {
        'form': form,
        'option_formset': option_formset,
        'case_formset': case_formset,
        'all_topics': Topic.objects.filter(bank__author=request.user).select_related('bank'),
        'is_create': True,
    })


@teacher_required
def task_detail(request, pk):
    task = get_object_or_404(Task, pk=pk, author=request.user)
    return render(request, 'tasks/task_detail.html', {'task': task})


@teacher_required
def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk, author=request.user)
    form = TaskForm(request.POST or None, request.FILES or None, instance=task, user=request.user)
    option_formset = AnswerOptionFormSet(
        request.POST or None,
        prefix='options',
        queryset=AnswerOption.objects.filter(task=task),
    )
    case_formset = TestCaseFormSet(
        request.POST or None,
        prefix='cases',
        queryset=TestCase.objects.filter(task=task),
    )
    if request.method == 'POST':
        if form.is_valid() and option_formset.is_valid() and case_formset.is_valid():
            saved_task = form.save(commit=False)
            formset_errors = _validate_formsets(saved_task, option_formset, case_formset)
            if not formset_errors:
                saved_task.save()
                _save_formsets(saved_task, option_formset, case_formset)
                messages.success(request, 'Задача обновлена.')
                return redirect('task_detail', pk=task.pk)
            for error in formset_errors:
                messages.error(request, error)
    return render(request, 'tasks/task_form.html', {
        'form': form,
        'option_formset': option_formset,
        'case_formset': case_formset,
        'all_topics': Topic.objects.filter(bank__author=request.user).select_related('bank'),
        'is_create': False,
        'task': task,
    })


@teacher_required
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk, author=request.user)
    if request.method == 'POST':
        task.delete()
        messages.success(request, 'Задача удалена.')
    return redirect('task_list')


@teacher_required
def lesson_list(request):
    lessons = Lesson.objects.filter(author=request.user).prefetch_related('entries')
    return render(request, 'tasks/lesson_list.html', {'lessons': lessons})


@teacher_required
def lesson_create(request):
    form = LessonForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        lesson = form.save(commit=False)
        lesson.author = request.user
        lesson.save()
        messages.success(request, 'Урок создан.')
        return redirect('lesson_detail', pk=lesson.pk)
    return render(request, 'tasks/lesson_form.html', {'form': form, 'is_create': True})


@teacher_required
def lesson_detail(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, author=request.user)
    add_task_form = AddTaskForm(lesson=lesson, user=request.user)
    return render(request, 'tasks/lesson_detail.html', {
        'lesson': lesson,
        'add_task_form': add_task_form,
    })


@teacher_required
def lesson_edit(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, author=request.user)
    form = LessonForm(request.POST or None, instance=lesson)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Урок обновлён.')
        return redirect('lesson_detail', pk=lesson.pk)
    return render(request, 'tasks/lesson_form.html', {'form': form, 'is_create': False, 'lesson': lesson})


@teacher_required
def lesson_delete(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, author=request.user)
    if request.method == 'POST':
        lesson.delete()
        messages.success(request, 'Урок удалён.')
    return redirect('lesson_list')


@teacher_required
def lesson_add_task(request, pk):
    lesson = get_object_or_404(Lesson, pk=pk, author=request.user)
    form = AddTaskForm(request.POST or None, lesson=lesson, user=request.user)
    if form.is_valid():
        LessonTask.objects.create(
            lesson=lesson,
            task=form.cleaned_data['task'],
            order=form.cleaned_data['order'],
        )
        messages.success(request, 'Задача добавлена в урок.')
    return redirect('lesson_detail', pk=pk)


@teacher_required
def lesson_remove_task(request, pk, task_id):
    lesson = get_object_or_404(Lesson, pk=pk, author=request.user)
    if request.method == 'POST':
        LessonTask.objects.filter(lesson=lesson, task_id=task_id).delete()
        messages.success(request, 'Задача удалена из урока.')
    return redirect('lesson_detail', pk=pk)
