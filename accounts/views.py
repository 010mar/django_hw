from django.contrib.auth.decorators import login_required
from django.shortcuts import render


def landing(request):
    return render(request, 'landing.html')


@login_required
def home(request):
    context = {
        'user_role': request.user.role,
    }
    return render(request, 'home.html', context)
