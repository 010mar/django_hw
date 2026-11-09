from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import teacher_required
from assignments.models import ClassGroup

from . import services
from .heatmap import build_heatmap


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
    child_users = [
        link.child for link in request.user.children.select_related('child')
    ]
    solved_map = services.solved_totals(child_users)
    children = [
        {'child': child, 'solved': solved_map.get(child.pk, 0)}
        for child in child_users
    ]
    return render(request, 'stats/parent_children.html', {'children': children})


@teacher_required
def class_stats(request, pk):
    class_group = get_object_or_404(ClassGroup, pk=pk, teacher=request.user)
    progress = services.class_progress(class_group)
    return render(request, 'stats/class_stats.html', {
        'class_group': class_group,
        'rows': progress['rows'],
        'class_percent': progress['class_percent'],
    })
