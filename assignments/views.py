import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts.decorators import teacher_required
from sandbox.runner import get_runner
from tasks.models import Task, TaskBlock

from .forms import AssignmentForm, ClassForm
from .models import Assignment, ClassGroup, Submission


def _visible_assignments(user):
    groups = user.class_groups.all()
    return (
        Assignment.objects
        .filter(Q(students=user) | Q(class_group__in=groups))
        .distinct()
    )


def _with_attempt_numbers(queryset):
    attempt_counts = (
        Submission.objects
        .filter(
            assignment=OuterRef('assignment'),
            task=OuterRef('task'),
            student=OuterRef('student'),
            created_at__lte=OuterRef('created_at'),
        )
        .values('assignment')
        .annotate(total=Count('pk'))
        .values('total')
    )
    return queryset.annotate(
        attempt_no=Subquery(attempt_counts, output_field=IntegerField())
    )


@teacher_required
def class_list(request):
    classes = ClassGroup.objects.filter(teacher=request.user).prefetch_related('students')
    return render(request, 'assignments/class_list.html', {'classes': classes})


@teacher_required
def class_create(request):
    form = ClassForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        class_group = form.save(commit=False)
        class_group.teacher = request.user
        class_group.save()
        messages.success(request, 'Класс создан. Теперь добавьте учеников.')
        return redirect('class_detail', pk=class_group.pk)
    return render(request, 'assignments/class_form.html', {'form': form, 'is_create': True})


@teacher_required
def class_detail(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    if request.method == 'POST':
        form = ClassForm(request.POST, instance=class_group)
        if form.is_valid():
            form.save()
            messages.success(request, 'Класс обновлён.')
        return redirect('class_detail', pk=class_group.pk)
    invite_url = request.build_absolute_uri(f'/classes/join/{class_group.invite_token}/')
    return render(request, 'assignments/class_detail.html', {
        'class_group': class_group,
        'invite_url': invite_url,
    })


@require_POST
@teacher_required
def class_add_student(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    username = request.POST.get('username', '').strip()
    if not username:
        messages.error(request, 'Введите логин ученика.')
        return redirect('class_detail', pk=class_group.pk)
    User = get_user_model()
    try:
        student = User.objects.get(username=username, role=User.Role.STUDENT)
    except User.DoesNotExist:
        messages.error(request, f'Ученик с логином «{username}» не найден.')
        return redirect('class_detail', pk=class_group.pk)
    if class_group.students.filter(pk=student.pk).exists():
        messages.warning(request, f'{student.username} уже в этом классе.')
    else:
        class_group.students.add(student)
        messages.success(request, f'{student.username} добавлен в класс.')
    return redirect('class_detail', pk=class_group.pk)


@require_POST
@teacher_required
def class_remove_student(request, pk, user_id):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    class_group.students.remove(user_id)
    messages.success(request, 'Ученик удалён из класса.')
    return redirect('class_detail', pk=class_group.pk)


@login_required
def class_join(request, token):
    class_group = get_object_or_404(ClassGroup, invite_token=token)
    user = request.user
    if not user.is_student:
        messages.error(request, 'Только ученики могут вступать в классы.')
        return redirect('home')
    if class_group.students.filter(pk=user.pk).exists():
        messages.info(request, f'Вы уже в классе «{class_group.title}».')
    else:
        class_group.students.add(user)
        messages.success(request, f'Вы вступили в класс «{class_group.title}».')
    return redirect('my_assignments')


@teacher_required
def class_delete(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    if request.method == 'POST':
        class_group.delete()
        messages.success(request, 'Класс удалён.')
    return redirect('class_list')


@teacher_required
def assignment_list(request):
    assignments = (
        Assignment.objects
        .filter(author=request.user)
        .select_related('class_group')
        .prefetch_related('tasks', 'students', 'class_group__students')
    )
    return render(request, 'assignments/assignment_list.html', {'assignments': assignments})


@teacher_required
def assignment_create(request):
    form = AssignmentForm(request.POST or None, author=request.user)
    if request.method == 'POST' and form.is_valid():
        assignment = form.save(commit=False)
        assignment.author = request.user
        assignment.save()
        tasks = set(form.cleaned_data['tasks'])
        lesson = form.cleaned_data.get('lesson')
        if lesson:
            tasks.update(lesson.tasks_ordered)
        assignment.tasks.set(tasks)
        assignment.students.set(form.cleaned_data['students'])
        messages.success(request, 'Задание создано.')
        return redirect('assignment_detail', pk=assignment.pk)
    return render(request, 'assignments/assignment_form.html', {'form': form, 'is_create': True})


@teacher_required
def assignment_detail(request, pk):
    assignment = get_object_or_404(
        Assignment.objects.select_related('class_group').prefetch_related(
            'tasks', 'class_group__students',
        ),
        pk=pk,
        author=request.user,
    )
    latest = {}
    for sub in (
        Submission.objects
        .filter(assignment=assignment)
        .select_related('student', 'task')
        .order_by('-created_at')
    ):
        latest.setdefault(sub.student_id, {})
        latest[sub.student_id].setdefault(sub.task_id, sub)
    students = assignment.effective_students
    tasks = assignment.tasks_ordered
    return render(request, 'assignments/assignment_detail.html', {
        'assignment': assignment,
        'students': students,
        'tasks': tasks,
        'latest': latest,
    })


@teacher_required
def assignment_delete(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, author=request.user)
    if request.method == 'POST':
        assignment.delete()
        messages.success(request, 'Задание удалено.')
    return redirect('assignment_list')


@teacher_required
def assignment_grade(request, pk):
    assignment = get_object_or_404(Assignment, pk=pk, author=request.user)
    submissions = _with_attempt_numbers(
        Submission.objects
        .filter(assignment=assignment, status=Submission.Status.PENDING)
        .select_related('student', 'task')
    ).order_by('-created_at')
    return render(request, 'assignments/assignment_grade.html', {
        'assignment': assignment,
        'submissions': submissions,
    })


@teacher_required
def grade_submission(request, submission_id):
    submission = get_object_or_404(Submission, pk=submission_id)
    action = request.POST.get('action')
    if request.method == 'POST' and action in ('accepted', 'rejected'):
        submission.status = Submission.Status.ACCEPTED if action == 'accepted' else Submission.Status.REJECTED
        submission.graded_by = request.user
        submission.save(update_fields=['status', 'graded_by'])
        messages.success(request, 'Оценка сохранена.')
    return redirect('assignment_grade', pk=submission.assignment_id)


@login_required
def my_assignments(request):
    assignments = list(
        _visible_assignments(request.user).prefetch_related('tasks')
    )
    solved_rows = (
        Submission.objects
        .filter(
            assignment__in=assignments,
            student=request.user,
            status__in=Submission.SOLVED_STATUSES,
        )
        .values('assignment_id')
        .annotate(solved=Count('task_id', distinct=True))
    )
    solved_map = {row['assignment_id']: row['solved'] for row in solved_rows}
    progress = {
        assignment.pk: {
            'solved': solved_map.get(assignment.pk, 0),
            'total': assignment.tasks.count(),
        }
        for assignment in assignments
    }
    return render(request, 'assignments/my_assignments.html', {
        'assignments': assignments,
        'progress': progress,
    })


@login_required
def assignment_solve(request, pk):
    assignment = get_object_or_404(_visible_assignments(request.user), pk=pk)
    submissions = {
        s.task_id: s
        for s in Submission.objects
        .filter(assignment=assignment, student=request.user)
        .select_related('task', 'answer_option')
        .order_by('task_id', '-created_at')
    }
    return render(request, 'assignments/assignment_solve.html', {
        'assignment': assignment,
        'tasks': assignment.tasks_ordered,
        'submissions': submissions,
    })


@login_required
def solve_task(request, assignment_id, task_id):
    assignment = get_object_or_404(_visible_assignments(request.user), pk=assignment_id)
    task = get_object_or_404(Task, pk=task_id, assignments=assignment)
    history = list(
        _with_attempt_numbers(
            Submission.objects.filter(
                assignment=assignment, task=task, student=request.user,
            ).select_related('answer_option')
        ).order_by('-created_at')[:5]
    )
    latest = history[0] if history else None

    if request.method == 'POST':
        if task.type == Task.Type.TEXT:
            submission = _solve_text_task(request, assignment, task)
        elif task.type == Task.Type.PROGRAMMING:
            submission = _solve_programming_task(request, assignment, task)
        else:
            submission = _solve_gap_task(request, assignment, task)
        messages.info(request, f'Результат: {submission.get_status_display()}')
        return redirect('solve_task', assignment_id=assignment.pk, task_id=task.pk)

    gap_blocks = _gap_block_items(task)
    context = {
        'assignment': assignment,
        'task': task,
        'latest': latest,
        'history': history,
        'gap_blocks': gap_blocks,
        'gap_grid': _gap_grid(gap_blocks),
    }
    return render(request, 'assignments/solve_task.html', context)


@teacher_required
def task_preview(request, task_id):
    task = get_object_or_404(Task, pk=task_id, author=request.user)
    gap_blocks = _gap_block_items(task)
    return render(request, 'assignments/solve_task.html', {
        'preview': True,
        'task': task,
        'latest': None,
        'history': [],
        'gap_blocks': gap_blocks,
        'gap_grid': _gap_grid(gap_blocks),
    })


def _gap_block_items(task):
    items = []
    number = 0
    for block in task.blocks.all():
        if block.kind == TaskBlock.Kind.GAP:
            number += 1
            items.append({'block': block, 'number': number})
        else:
            items.append({'block': block, 'number': None})
    return items


BR_TAG_PATTERN = re.compile(r'<br\s*/?>', re.IGNORECASE)


def _gap_grid(items):
    rows = []
    current = []
    for item in items:
        block = item['block']
        if block.kind == TaskBlock.Kind.TEXT:
            if current and BR_TAG_PATTERN.search(block.text or ''):
                rows.append(current)
                current = []
        else:
            current.append(item)
    if current:
        rows.append(current)

    columns = max((len(row) for row in rows), default=0)
    grid_rows = []
    for number, row in enumerate(rows, start=1):
        cells = list(row) + [None] * (columns - len(row))
        grid_rows.append({'number': number, 'cells': cells})
    return {'rows': grid_rows, 'columns': list(range(1, columns + 1))}


def _solve_text_task(request, assignment, task):
    if task.answer_mode == Task.AnswerMode.CHOICE:
        option_id = request.POST.get('answer_option')
        option = get_object_or_404(task.answer_options, pk=option_id)
        status = Submission.Status.CORRECT if option.is_correct else Submission.Status.INCORRECT
        return Submission.objects.create(
            assignment=assignment, task=task, student=request.user,
            answer_option=option, status=status,
        )
    answer_text = request.POST.get('answer_text', '')
    status = (
        Submission.Status.CORRECT
        if task.is_short_answer_correct(answer_text)
        else Submission.Status.INCORRECT
    )
    return Submission.objects.create(
        assignment=assignment, task=task, student=request.user,
        answer_text=answer_text, status=status,
    )


def _solve_programming_task(request, assignment, task):
    code = request.POST.get('code', '')
    tests = list(task.test_cases.all().order_by('order', 'id'))
    if not tests:
        return Submission.objects.create(
            assignment=assignment, task=task, student=request.user,
            code=code, status=Submission.Status.WA,
            details='У задачи не настроены тесты. Обратитесь к учителю.',
        )
    runner = get_runner()
    details_lines = []
    final_verdict = Submission.Status.OK
    for test in tests:
        result = runner.check(
            code,
            input_data=test.input_data,
            expected_output=test.expected_output,
            time_limit_ms=task.time_limit_ms,
            memory_limit_mb=task.memory_limit_mb,
        )
        label = 'Открытый' if test.is_public else 'Скрытый'
        if result.verdict == 'ok':
            details_lines.append(f'Тест {label}: OK')
        elif result.verdict == 'tle':
            final_verdict = Submission.Status.TLE
            details_lines.append(f'Тест {label}: превышено время')
            break
        elif result.verdict == 're':
            final_verdict = Submission.Status.RE
            details_lines.append(f'Тест {label}: ошибка выполнения\n{result.details}')
            break
        elif result.verdict == 'ce':
            final_verdict = Submission.Status.CE
            details_lines.append(f'Ошибка компиляции\n{result.details}')
            break
        else:
            final_verdict = Submission.Status.WA
            details_lines.append(f'Тест {label}: неправильный ответ\n{result.details}')
            break
    return Submission.objects.create(
        assignment=assignment, task=task, student=request.user,
        code=code, status=final_verdict, details='\n'.join(details_lines),
    )


def _solve_gap_task(request, assignment, task):
    gap_blocks = list(task.blocks.filter(kind=TaskBlock.Kind.GAP))
    answers = {}
    details = []
    all_correct = bool(gap_blocks)
    for index, gap in enumerate(gap_blocks, start=1):
        value = request.POST.get(f'gap_{index}', '')
        answers[str(index)] = value
        if gap.is_correct(value):
            details.append(f'Пропуск {index}: верно')
        else:
            all_correct = False
            details.append(f'Пропуск {index}: неверно')
    return Submission.objects.create(
        assignment=assignment, task=task, student=request.user,
        gap_answers=answers,
        status=Submission.Status.CORRECT if all_correct else Submission.Status.INCORRECT,
        details='\n'.join(details),
    )
