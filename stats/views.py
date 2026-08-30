from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required
from assignments.models import ClassGroup, Submission

from .heatmap import build_heatmap
from . import services


def _can_view_student(user, student) -> bool:
    if user == student or user.is_teacher:
        return True
    return user.children.filter(child=student).exists()


def _get_visible_student(user, pk):
    student = get_object_or_404(
        get_user_model().objects.filter(role='student'),
        pk=pk,
    )
    if not _can_view_student(user, student):
        raise Http404
    return student


@login_required
def my_stats(request):
    if not request.user.is_student:
        messages.warning(request, 'Эта страница доступна только ученику.')
        return redirect('home')
    return render(request, 'stats/student_stats.html', {
        'student': request.user,
        'stats': services.student_stats(request.user),
        'heatmap': build_heatmap(services.solved_counts_by_day(request.user)),
    })


@login_required
def student_stats(request, pk):
    student = _get_visible_student(request.user, pk)
    return render(request, 'stats/student_stats.html', {
        'student': student,
        'stats': services.student_stats(student),
        'heatmap': build_heatmap(services.solved_counts_by_day(student)),
    })


@login_required
def parent_children(request):
    if not request.user.is_parent:
        messages.warning(request, 'Эта страница доступна только родителю.')
        return redirect('home')
    children = []
    for link in request.user.children.select_related('child'):
        children.append({
            'child': link.child,
            'solved': services.solved_total(link.child),
        })
    return render(request, 'stats/parent_children.html', {'children': children})


@teacher_required
def class_stats(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    rows = []
    for student in class_group.students.all():
        progress = services.assignment_progress(
            student,
            assignments=class_group.assignments.all(),
        )
        solved = sum(item['solved'] for item in progress)
        total = sum(item['total'] for item in progress)
        rows.append({
            'student': student,
            'solved': solved,
            'total': total,
            'percent': round(solved / total * 100) if total else 0,
        })
    totals = [row['total'] for row in rows if row['total']]
    class_percent = (
        round(sum(row['percent'] for row in rows) / len(rows))
        if rows else 0
    )
    return render(request, 'stats/class_stats.html', {
        'class_group': class_group,
        'rows': rows,
        'class_percent': class_percent,
    })
