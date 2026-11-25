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


def _find_course(courses, value):
    if value.isdigit():
        return next(
            (course for course in courses if course.pk == int(value)),
            None,
        )
    return None


def _stats_page_context(request, student):
    courses = list(services.student_courses(student))
    selected_course = _find_course(courses, request.GET.get('course', ''))
    chart_course = selected_course
    if 'chart_course' in request.GET:
        chart_course = _find_course(
            courses, request.GET.get('chart_course', ''),
        )
    stats = services.student_stats(student, course=selected_course)
    return {
        'student': student,
        'stats': stats,
        'heatmap': build_heatmap(stats['heatmap']),
        'task_chart': services.task_results_chart(
            student, course=chart_course,
        ),
        'courses': courses,
        'selected_course': selected_course,
        'chart_course': chart_course,
    }


@login_required
def my_stats(request):
    if not request.user.is_student:
        messages.warning(request, 'Эта страница доступна только ученику.')
        return redirect('home')
    return render(
        request,
        'stats/student_stats.html',
        _stats_page_context(request, request.user),
    )


@login_required
def student_stats(request, pk):
    student = _get_visible_student(request.user, pk)
    return render(
        request,
        'stats/student_stats.html',
        _stats_page_context(request, student),
    )


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
