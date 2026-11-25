from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from assignments.models import Submission
from assignments.views import _visible_assignments
from tasks.forms import task_number_sort_key
from tasks.models import Course, Task


def _course_condition(course):
    return (
        Q(lesson__module__course=course)
        | Q(assignment__class_group__course=course)
        | Q(assignment__lesson__module__course=course)
    )


def student_courses(student):
    return (
        Course.objects
        .filter(
            Q(class_groups__students=student)
            | Q(modules__lessons__submissions__student=student)
        )
        .distinct()
    )


def _course_tasks_condition(courses):
    return (
        Q(lesson_entries__lesson__module__course__in=courses)
        | Q(assignments__lesson__module__course__in=courses)
        | Q(assignments__class_group__course__in=courses)
    )


def _count_level(count: int) -> int:
    if count <= 0:
        return 0
    if count == 1:
        return 1
    if count <= 3:
        return 2
    return 3


def task_results_by_topic(student, course=None) -> list:
    submissions = Submission.objects.filter(student=student)
    if course is not None:
        submissions = submissions.filter(_course_condition(course))
        courses = Course.objects.filter(pk=course.pk)
    else:
        courses = student_courses(student)

    tasks = (
        Task.objects
        .filter(
            _course_tasks_condition(courses)
            | Q(pk__in=submissions.values('task_id'))
        )
        .select_related('topic')
        .distinct()
    )

    counts = {
        row['task_id']: row
        for row in submissions
        .values('task_id')
        .annotate(
            attempts=Count('pk'),
            correct=Count(
                'pk', filter=Q(status__in=Submission.SOLVED_STATUSES),
            ),
        )
    }

    groups = {}
    for task in tasks:
        row = counts.get(task.pk, {})
        item = {
            'task': task,
            'label': task.task_number or str(task.pk),
            'attempts': row.get('attempts', 0),
            'correct': row.get('correct', 0),
        }
        item['attempt_level'] = _count_level(item['attempts'])
        item['correct_level'] = _count_level(item['correct'])
        group = groups.setdefault(
            task.topic_id,
            {'topic': task.topic, 'tasks': []},
        )
        group['tasks'].append(item)

    result = []
    for group in groups.values():
        topic = group['topic']
        group['title'] = topic.name if topic else 'Без темы'
        group['order_key'] = (
            (1, 0, '') if topic is None else (0, topic.order, topic.name)
        )
        group['tasks'].sort(
            key=lambda item: (
                task_number_sort_key(item['task'].task_number or ''),
                item['task'].title,
            )
        )
        result.append(group)
    result.sort(key=lambda group: group['order_key'])
    return result


def solved_counts_by_day(student, course=None) -> dict:
    submissions = Submission.objects.filter(
        student=student, status__in=Submission.SOLVED_STATUSES,
    )
    if course is not None:
        submissions = submissions.filter(_course_condition(course))
    rows = (
        submissions
        .annotate(
            day=TruncDate(
                'created_at', tzinfo=timezone.get_current_timezone(),
            )
        )
        .values('day')
        .annotate(total=Count('pk'))
    )
    return {row['day']: row['total'] for row in rows}


def activity_streaks(counts: dict) -> dict:
    today = timezone.localdate()
    days = sorted(
        day for day, total in counts.items()
        if total > 0 and day <= today
    )
    longest = 0
    run = 0
    previous = None
    for day in days:
        if previous is not None and day == previous + timedelta(days=1):
            run += 1
        else:
            run = 1
        longest = max(longest, run)
        previous = day

    current = 0
    if days and days[-1] >= today - timedelta(days=1):
        active_days = set(days)
        cursor = days[-1]
        current = 1
        while cursor - timedelta(days=1) in active_days:
            current += 1
            cursor -= timedelta(days=1)

    return {'current': current, 'longest': longest, 'today': today}


def solved_total(student, course=None) -> int:
    submissions = Submission.objects.filter(
        student=student,
        status__in=Submission.SOLVED_STATUSES,
    )
    if course is not None:
        submissions = submissions.filter(_course_condition(course))
    return submissions.values('assignment_id', 'task_id').distinct().count()


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


def student_stats(student, course=None) -> dict:
    counts = solved_counts_by_day(student, course=course)
    streaks = activity_streaks(counts)
    return {
        'solved_total': solved_total(student, course=course),
        'assignment_progress': assignment_progress(student),
        'heatmap': counts,
        'current_streak': streaks['current'],
        'longest_streak': streaks['longest'],
    }
