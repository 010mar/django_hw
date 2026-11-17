from django import template

register = template.Library()


@register.filter
def plural_ru(value, forms):
    try:
        number = abs(int(value))
    except (TypeError, ValueError):
        return ''
    one, few, many = [form.strip() for form in forms.split(',')]
    if number % 100 in (11, 12, 13, 14):
        return many
    last = number % 10
    if last == 1:
        return one
    if last in (2, 3, 4):
        return few
    return many
