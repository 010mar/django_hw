from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    if mapping is None:
        return None
    if hasattr(mapping, 'get'):
        return mapping.get(key)
    try:
        return mapping[key]
    except (IndexError, KeyError, TypeError):
        return None
