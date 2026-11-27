import mimetypes
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import SuspiciousFileOperation
from django.db.models import Q
from django.http import FileResponse, Http404
from django.utils._os import safe_join
from django.views.decorators.http import require_GET

from accounts.models import ParentLink
from assignments.models import Submission
from tasks.models import Task, TaskAttachment, TaskImage


def _can_access_task(user, task):
    if user.is_staff:
        return True
    if task.author_id == user.pk:
        return True
    if user.is_teacher:
        return Task.objects.filter(
            Q(pk=task.pk, assignments__author=user)
            | Q(
                pk=task.pk,
                lesson_entries__lesson__module__course__class_groups__teacher=user,
            )
        ).exists()
    if user.is_parent:
        return Task.objects.filter(
            pk=task.pk,
            submissions__student__parent_links__parent=user,
        ).exists()
    return Task.objects.filter(
        Q(pk=task.pk, submissions__student=user)
        | Q(pk=task.pk, assignments__students=user)
        | Q(pk=task.pk, assignments__class_group__students=user)
        | Q(
            pk=task.pk,
            lesson_entries__lesson__module__course__class_groups__students=user,
        )
    ).exists()


def _can_access_submission(user, submission):
    if user.is_staff or submission.student_id == user.pk:
        return True
    if user.is_parent:
        return ParentLink.objects.filter(
            parent=user, child_id=submission.student_id,
        ).exists()
    if not user.is_teacher:
        return False
    assignment = submission.assignment
    if assignment is not None:
        if assignment.author_id == user.pk:
            return True
        if (
            assignment.class_group_id
            and assignment.class_group.teacher_id == user.pk
        ):
            return True
    lesson = submission.lesson
    if lesson is not None:
        if lesson.author_id == user.pk:
            return True
        if (
            lesson.module_id
            and lesson.module.course.class_groups.filter(teacher=user).exists()
        ):
            return True
    return False


def _authorize(user, path):
    if path.startswith('avatars/'):
        return {}
    if path.startswith('submissions/'):
        submission = Submission.objects.filter(image=path).first()
        if submission is None or not _can_access_submission(user, submission):
            raise Http404
        return {}
    if path.startswith('tasks/inline/'):
        image = TaskImage.objects.filter(image=path).first()
        if image is None:
            raise Http404
        if image.task_id is not None:
            if not _can_access_task(user, image.task):
                raise Http404
        elif image.author_id != user.pk and not user.is_staff:
            raise Http404
        return {}
    if path.startswith('tasks/files/'):
        attachment = TaskAttachment.objects.filter(file=path).first()
        if attachment is None or not _can_access_task(user, attachment.task):
            raise Http404
        return {'as_attachment': True, 'filename': attachment.filename}
    if path.startswith('tasks/'):
        task = Task.objects.filter(image=path).first()
        if task is None or not _can_access_task(user, task):
            raise Http404
        return {}
    if not user.is_staff:
        raise Http404
    return {}


@login_required
@require_GET
def serve_media(request, path):
    normalized = path.replace('\\', '/').lstrip('/')
    if not normalized:
        raise Http404
    response_kwargs = _authorize(request.user, normalized)

    try:
        full_path = safe_join(str(settings.MEDIA_ROOT), normalized)
    except (SuspiciousFileOperation, ValueError):
        raise Http404 from None
    if not Path(full_path).is_file():
        raise Http404

    content_type = mimetypes.guess_type(full_path)[0]
    response = FileResponse(
        open(full_path, 'rb'),  # noqa: SIM115 - FileResponse closes the handle
        content_type=content_type or 'application/octet-stream',
        **response_kwargs,
    )
    response['Cache-Control'] = 'private, max-age=0, must-revalidate'
    return response
