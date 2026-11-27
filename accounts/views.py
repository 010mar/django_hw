from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from tasks.models import Course

from .forms import ProfileForm


def landing(request):
    if request.user.is_authenticated:
        return redirect('home')
    return redirect('account_login')


@login_required
def home(request):
    context = {}
    if request.user.is_student:
        courses = (
            Course.objects
            .filter(class_groups__students=request.user)
            .distinct()
            .prefetch_related('modules__lessons')
        )
        context['student_courses'] = [
            {
                'course': course,
                'classes': list(
                    course.class_groups.filter(students=request.user)
                ),
            }
            for course in courses
        ]
    return render(request, 'home.html', context)


@login_required
def profile(request):
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Профиль обновлён.')
            return redirect('profile')
    else:
        form = ProfileForm(instance=request.user)

    children = []
    if request.user.is_parent:
        children = request.user.children.select_related('child').order_by(
            'child__last_name', 'child__first_name', 'child__username'
        )

    return render(
        request,
        'account/profile.html',
        {'form': form, 'children': children},
    )
