from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from assignments.models import Submission
from assignments.views import _visible_assignments


def solved_counts_by_day(student) -> dict:
    rows = (
        Submission.objects
        .filter(student=student, status__in=Submission.SOLVED_STATUSES)
        .annotate(
            day=TruncDate(
                'created_at', tzinfo=timezone.get_current_timezone(),
            )
        )
        .values('day')
        .annotate(total=Count('pk'))
    )
    return {row['day']: row['total'] for row in rows}


def solved_total(student) -> int:
    return Submission.objects.filter(
        student=student,
        status__in=Submission.SOLVED_STATUSES,
    ).values('assignment_id', 'task_id').distinct().count()


def solved_totals(students) -> dict:
    rows = (
        Submission.objects
        .filter(student__in=students, status__in=Submission.SOLVED_STATUSES)
        .values('student_id', 'assignment_id', 'task_id')
        .distinct()
    )
    counts = {}
    for row in rows:
        counts[row['student_id']] = counts.get(row['student_id'], 0) + 1
    return counts


def assignment_progress(student, assignments=None) -> list:
    if assignments is None:
        assignments = _visible_assignments(student)
    assignments = list(assignments.prefetch_related('tasks'))
    solved_rows = (
        Submission.objects
        .filter(
            assignment__in=assignments,
            student=student,
            status__in=Submission.SOLVED_STATUSES,
        )
        .values('assignment_id')
        .annotate(solved=Count('task_id', distinct=True))
    )
    solved_map = {row['assignment_id']: row['solved'] for row in solved_rows}
    result = []
    for assignment in assignments:
        solved = solved_map.get(assignment.pk, 0)
        total = assignment.tasks.count()
        result.append({
            'assignment': assignment,
            'solved': solved,
            'total': total,
            'percent': round(solved / total * 100) if total else 0,
        })
    return result


def class_progress(class_group) -> dict:
    students = list(class_group.students.all())
    assignments = list(class_group.assignments.prefetch_related('tasks'))
    totals = {
        assignment.pk: assignment.tasks.count()
        for assignment in assignments
    }
    solved_rows = (
        Submission.objects
        .filter(
            assignment__in=assignments,
            student__in=students,
            status__in=Submission.SOLVED_STATUSES,
        )
        .values('student_id', 'assignment_id')
        .annotate(solved=Count('task_id', distinct=True))
    )
    solved_map = {
        (row['student_id'], row['assignment_id']): row['solved']
        for row in solved_rows
    }
    total = sum(totals.values())
    rows = []
    for student in students:
        solved = sum(
            solved_map.get((student.pk, assignment.pk), 0)
            for assignment in assignments
        )
        rows.append({
            'student': student,
            'solved': solved,
            'total': total,
            'percent': round(solved / total * 100) if total else 0,
        })
    class_percent = (
        round(sum(row['percent'] for row in rows) / len(rows))
        if rows else 0
    )
    return {'rows': rows, 'class_percent': class_percent}


def student_stats(student) -> dict:
    return {
        'solved_total': solved_total(student),
        'assignment_progress': assignment_progress(student),
        'heatmap': solved_counts_by_day(student),
    }
