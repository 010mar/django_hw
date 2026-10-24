from django import template
from django.utils.html import conditional_escape, linebreaks
from django.utils.safestring import mark_safe

from tasks.models import IMAGE_TOKEN_PATTERN, TaskImage

register = template.Library()


@register.filter
def render_task_body(value, task=None):
    if not value:
        return ''
    text = conditional_escape(value)

    def replace(match):
        if task is None:
            return ''
        image = TaskImage.objects.filter(token=match.group(1), task=task).first()
        if image is None:
            return ''
        return (
            f'<img src="{conditional_escape(image.image.url)}" '
            'alt="Изображение к условию" class="img-fluid rounded my-2 d-block">'
        )

    text = IMAGE_TOKEN_PATTERN.sub(replace, text)
    return mark_safe(linebreaks(text, autoescape=False))
