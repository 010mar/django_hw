import re

from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path

from config.media import serve_media

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('allauth.urls')),
    path('', include('accounts.urls')),
    path('', include('tasks.urls')),
    path('', include('assignments.urls')),
    path('', include('stats.urls')),
    re_path(
        r'^{}(?P<path>.*)$'.format(re.escape(settings.MEDIA_URL.lstrip('/'))),
        serve_media,
        name='protected_media',
    ),
]
