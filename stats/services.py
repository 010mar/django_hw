from django.utils import timezone

from assignments.models import Submission
from assignments.views import _visible_assignments


def solved_counts_by_day(student) -> dict:
    counts = {}
    rows = Submission.objects.filter(
        student=student,
        status__in=Submission.SOLVED_STATUSES,
    ).values_list('created_at', flat=True)
    for created_at in rows:
        day = timezone.localdate(created_at)
        counts[day] = counts.get(day, 0) + 1
    return counts


def solved_total(student) -> int:
    return Submission.objects.filter(
        student=student,
        status__in=Submission.SOLVED_STATUSES,
    ).values('assignment_id', 'task_id').distinct().count()


def assignment_progress(student, assignments=None) -> list:
    result = []
    if assignments is None:
        assignments = _visible_assignments(student)
    assignments = assignments.prefetch_related('tasks')
    for assignment in assignments:
        solved = Submission.objects.filter(
            assignment=assignment,
            student=student,
            status__in=Submission.SOLVED_STATUSES,
        ).values('task_id').distinct().count()
        total = assignment.tasks.count()
        result.append({
            'assignment': assignment,
            'solved': solved,
            'total': total,
            'percent': round(solved / total * 100) if total else 0,
        })
    return result


def student_stats(student) -> dict:
    return {
        'solved_total': solved_total(student),
        'assignment_progress': assignment_progress(student),
        'heatmap': solved_counts_by_day(student),
    }
