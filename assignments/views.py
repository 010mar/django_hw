from django.contrib import messages
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required
from sandbox.runner import get_runner
from tasks.models import Task

from .forms import AssignmentForm, ClassForm
from .models import Assignment, ClassGroup, Submission


def _visible_assignments(user):
    from django.db.models import Q

    groups = user.class_groups.all()
    return (
        Assignment.objects
        .filter(Q(students=user) | Q(class_group__in=groups))
        .distinct()
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
        form.save_m2m()
        messages.success(request, 'Класс создан.')
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
    all_students = get_user_model().objects.filter(role='student').order_by('last_name', 'first_name')
    return render(request, 'assignments/class_detail.html', {
        'class_group': class_group,
        'all_students': all_students,
    })


@teacher_required
def class_delete(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    if request.method == 'POST':
        class_group.delete()
        messages.success(request, 'Класс удалён.')
    return redirect('class_list')


@teacher_required
def assignment_list(request):
    assignments = Assignment.objects.filter(author=request.user).prefetch_related('tasks', 'class_group')
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
        Assignment.objects.prefetch_related('tasks', 'class_group'),
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
    submissions = (
        Submission.objects
        .filter(assignment=assignment, task__type=Task.Type.IMAGE)
        .select_related('student', 'task')
        .exclude(status__in=[Submission.Status.CORRECT, Submission.Status.INCORRECT,
                             Submission.Status.OK, Submission.Status.WA,
                             Submission.Status.TLE, Submission.Status.RE, Submission.Status.CE])
        .order_by('-created_at')
    )
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


def my_assignments(request):
    assignments = _visible_assignments(request.user).prefetch_related('tasks', 'class_group')
    progress = {}
    for assignment in assignments:
        solved = Submission.objects.filter(
            assignment=assignment,
            student=request.user,
            status__in=Submission.SOLVED_STATUSES,
        ).values('task_id').distinct().count()
        progress[assignment.pk] = {
            'solved': solved,
            'total': assignment.tasks.count(),
        }
    return render(request, 'assignments/my_assignments.html', {
        'assignments': assignments,
        'progress': progress,
    })


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


def solve_task(request, assignment_id, task_id):
    assignment = get_object_or_404(_visible_assignments(request.user), pk=assignment_id)
    task = get_object_or_404(Task, pk=task_id, assignments=assignment)
    history = Submission.objects.filter(
        assignment=assignment, task=task, student=request.user,
    ).select_related('answer_option').order_by('-created_at')[:5]
    latest = history.first() if history else None

    if request.method == 'POST':
        if task.type == Task.Type.TEXT:
            submission = _solve_text_task(request, assignment, task)
        elif task.type == Task.Type.PROGRAMMING:
            submission = _solve_programming_task(request, assignment, task)
        else:
            submission = _solve_image_task(request, assignment, task)
        messages.info(request, f'Результат: {submission.get_status_display()}')
        return redirect('solve_task', assignment_id=assignment.pk, task_id=task.pk)

    context = {
        'assignment': assignment,
        'task': task,
        'latest': latest,
        'history': history,
    }
    return render(request, 'assignments/solve_task.html', context)


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
    runner = get_runner()
    details_lines = []
    final_verdict = Submission.Status.OK
    for test in task.test_cases.all().order_by('order', 'id'):
        result = runner.check(
            code,
            input_data=test.input_data,
            expected_output=test.expected_output,
            time_limit_ms=task.time_limit_ms,
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


def _solve_image_task(request, assignment, task):
    image = request.FILES.get('image')
    return Submission.objects.create(
        assignment=assignment, task=task, student=request.user,
        image=image, status=Submission.Status.PENDING,
    )
