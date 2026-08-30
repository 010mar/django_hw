from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def teacher_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not request.user.is_teacher:
            messages.warning(request, 'Эта страница доступна только учителю.')
            return redirect('home')
        return view_func(request, *args, **kwargs)

    return wrapper
