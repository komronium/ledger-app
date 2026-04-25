from django import template

register = template.Library()


@register.filter
def is_admin(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    try:
        return user.profile.role == 'admin'
    except Exception:
        return True


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key, 0)


@register.filter
def format_currency(value):
    if value is None:
        return ''
    try:
        value = float(value)
        return '{:,.0f}'.format(value).replace(',', ' ')
    except (ValueError, TypeError):
        return value


@register.filter
def pct(value, total):
    try:
        return min(100, round(float(value) / float(total) * 100))
    except (ValueError, ZeroDivisionError, TypeError):
        return 0
