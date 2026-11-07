from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import ParentLinkForm, ProfileForm
from .models import ParentLink


def landing(request):
    return render(request, 'landing.html')


@login_required
def home(request):
    return render(request, 'home.html')


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
    child_form = None
    if request.user.is_parent:
        children = request.user.children.select_related('child').order_by(
            'child__last_name', 'child__first_name', 'child__username'
        )
        child_form = ParentLinkForm(parent=request.user)

    return render(
        request,
        'account/profile.html',
        {'form': form, 'children': children, 'child_form': child_form},
    )


@login_required
@require_POST
def add_child(request):
    if not request.user.is_parent:
        raise PermissionDenied
    form = ParentLinkForm(request.POST, parent=request.user)
    if form.is_valid():
        form.save()
        messages.success(request, 'Ученик привязан к профилю.')
    else:
        for errors in form.errors.values():
            for error in errors:
                messages.error(request, error)
    return redirect('profile')


@login_required
@require_POST
def remove_child(request, pk):
    link = get_object_or_404(ParentLink, pk=pk, parent=request.user)
    link.delete()
    messages.success(request, 'Привязка удалена.')
    return redirect('profile')
