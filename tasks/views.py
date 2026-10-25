from PIL import Image
from django.contrib import messages
from django.db.models import Max, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required

from .forms import (
    AddTaskForm,
    AnswerOptionFormSet,
    CourseForm,
    CourseModuleForm,
    LessonForm,
    TaskBankForm,
    TaskForm,
    TestCaseFormSet,
    TopicForm,
)
from .models import (
    IMAGE_TOKEN_PATTERN,
    AnswerOption,
    Course,
    CourseModule,
    Lesson,
    LessonTask,
    Task,
    TaskBank,
    TaskImage,
    TestCase,
    Topic,
)

MAX_INLINE_IMAGE_SIZE = 10 * 1024 * 1024


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

    task_number = request.GET.get('task_number', '').strip()
    if task_number:
        try:
            task = Task.objects.get(pk=int(task_number), bank=bank, author=request.user)
            return redirect('task_detail', pk=task.pk)
        except (ValueError, Task.DoesNotExist):
            pass

    tasks = bank.tasks.select_related('author').all()
    topics = bank.topics.all()

    topic_id = request.GET.get('topic_id', '').strip()
    current_topic = None
    if topic_id:
        try:
            current_topic = topics.get(pk=int(topic_id))
            tasks = tasks.filter(topic=current_topic)
        except (ValueError, Topic.DoesNotExist):
            pass

    return render(request, 'tasks/bank_detail.html', {
        'bank': bank,
        'topics': topics,
        'tasks': tasks,
        'current_topic': current_topic,
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
                last_order = bank.topics.aggregate(Max('order'))['order__max'] or 0
                topic.order = last_order + 1
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


def _inline_images_for_request(request, task=None):
    if request.method == 'POST':
        tokens = set(IMAGE_TOKEN_PATTERN.findall(request.POST.get('body', '')))
        return TaskImage.objects.filter(author=request.user, token__in=tokens)
    if task is not None:
        return task.inline_images.all()
    return TaskImage.objects.none()


def _sync_task_images(task):
    tokens = set(IMAGE_TOKEN_PATTERN.findall(task.body or ''))
    for image in task.inline_images.all():
        if str(image.token) not in tokens:
            image.delete()
    if tokens:
        TaskImage.objects.filter(
            token__in=tokens,
            author=task.author,
            task__isnull=True,
        ).update(task=task)


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
            topic = form.cleaned_data.get('topic')
            if topic:
                last_num = (
                    Task.objects
                    .filter(topic=topic)
                    .exclude(task_number='')
                    .values_list('task_number', flat=True)
                )
                max_seq = 0
                prefix = f'{topic.order}_'
                for num in last_num:
                    if num.startswith(prefix):
                        try:
                            seq = int(num[len(prefix):])
                            if seq >= 1:
                                max_seq = max(max_seq, seq)
                        except ValueError:
                            pass
                task.task_number = f'{prefix}{max_seq + 1}'
            else:
                task.task_number = ''
            task.title = task.task_number or 'Без номера'
            formset_errors = _validate_formsets(task, option_formset, case_formset)
            if not formset_errors:
                task.save()
                _sync_task_images(task)
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
        'inline_images': _inline_images_for_request(request),
        'is_create': True,
    })


@teacher_required
def task_number_preview(request):
    topic_id = request.GET.get('topic_id')
    if not topic_id:
        return JsonResponse({'task_number': ''})
    try:
        topic = Topic.objects.get(pk=topic_id, bank__author=request.user)
    except Topic.DoesNotExist:
        return JsonResponse({'task_number': ''})
    last_num = (
        Task.objects
        .filter(topic=topic)
        .exclude(task_number='')
        .values_list('task_number', flat=True)
    )
    max_seq = 0
    prefix = f'{topic.order}_'
    for num in last_num:
        if num.startswith(prefix):
            try:
                seq = int(num[len(prefix):])
                if seq >= 1:
                    max_seq = max(max_seq, seq)
            except ValueError:
                pass
    return JsonResponse({'task_number': f'{prefix}{max_seq + 1}'})


@teacher_required
def task_image_upload(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не поддерживается.'}, status=405)
    upload = request.FILES.get('image')
    if upload is None:
        return JsonResponse({'error': 'Файл не передан.'}, status=400)
    if upload.size > MAX_INLINE_IMAGE_SIZE:
        return JsonResponse(
            {'error': 'Изображение не должно превышать 10 МБ.'},
            status=400,
        )
    try:
        image = Image.open(upload)
        image.verify()
    except Exception:
        return JsonResponse(
            {'error': 'Не удалось распознать изображение.'},
            status=400,
        )
    upload.seek(0)
    task_image = TaskImage.objects.create(author=request.user, image=upload)
    return JsonResponse({
        'token': str(task_image.token),
        'url': task_image.image.url,
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
                _sync_task_images(saved_task)
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
        'inline_images': _inline_images_for_request(request, task),
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
    course_id = lesson.module.course_id if lesson.module_id else None
    if request.method == 'POST':
        lesson.delete()
        messages.success(request, 'Урок удалён.')
    if course_id:
        return redirect('course_detail', pk=course_id)
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


@teacher_required
def course_list(request):
    courses = (
        Course.objects
        .filter(author=request.user)
        .prefetch_related('modules__lessons')
    )
    return render(request, 'tasks/course_list.html', {'courses': courses})


@teacher_required
def course_create(request):
    form = CourseForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        course = form.save(commit=False)
        course.author = request.user
        course.save()
        messages.success(request, 'Курс создан.')
        return redirect('course_detail', pk=course.pk)
    return render(request, 'tasks/course_form.html', {'form': form, 'is_create': True})


@teacher_required
def course_detail(request, pk):
    course = get_object_or_404(Course, pk=pk, author=request.user)
    modules = course.modules.prefetch_related(
        Prefetch('lessons', queryset=Lesson.objects.order_by('order', 'created_at'))
    )
    return render(request, 'tasks/course_detail.html', {
        'course': course,
        'modules': modules,
        'module_form': CourseModuleForm(),
    })


@teacher_required
def course_edit(request, pk):
    course = get_object_or_404(Course, pk=pk, author=request.user)
    form = CourseForm(request.POST or None, instance=course)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Курс обновлён.')
        return redirect('course_detail', pk=course.pk)
    return render(request, 'tasks/course_form.html', {
        'form': form,
        'course': course,
        'is_create': False,
    })


@teacher_required
def course_delete(request, pk):
    course = get_object_or_404(Course, pk=pk, author=request.user)
    if request.method == 'POST':
        course.delete()
        messages.success(request, 'Курс удалён.')
    return redirect('course_list')


@teacher_required
def module_create(request, pk):
    course = get_object_or_404(Course, pk=pk, author=request.user)
    if request.method == 'POST':
        form = CourseModuleForm(request.POST)
        if form.is_valid():
            module = form.save(commit=False)
            module.course = course
            module.order = (
                course.modules.aggregate(Max('order'))['order__max'] or 0
            ) + 1
            module.save()
            messages.success(request, 'Модуль добавлен.')
        else:
            messages.error(request, 'Не удалось добавить модуль. Проверьте название и дату.')
    return redirect('course_detail', pk=course.pk)


@teacher_required
def module_edit(request, pk):
    module = get_object_or_404(CourseModule, pk=pk, course__author=request.user)
    form = CourseModuleForm(request.POST or None, instance=module)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Модуль обновлён.')
        return redirect('course_detail', pk=module.course_id)
    return render(request, 'tasks/module_form.html', {
        'form': form,
        'module': module,
        'course': module.course,
    })


@teacher_required
def module_delete(request, pk):
    module = get_object_or_404(CourseModule, pk=pk, course__author=request.user)
    course_id = module.course_id
    if request.method == 'POST':
        module.delete()
        messages.success(request, 'Модуль удалён.')
    return redirect('course_detail', pk=course_id)


@teacher_required
def module_lesson_create(request, pk):
    module = get_object_or_404(CourseModule, pk=pk, course__author=request.user)
    if request.method == 'POST':
        form = LessonForm(request.POST)
        if form.is_valid():
            lesson = form.save(commit=False)
            lesson.module = module
            lesson.author = request.user
            lesson.order = (
                module.lessons.aggregate(Max('order'))['order__max'] or 0
            ) + 1
            lesson.save()
            messages.success(request, 'Урок добавлен.')
        else:
            messages.error(request, 'Укажите название урока.')
    return redirect('course_detail', pk=module.course_id)
