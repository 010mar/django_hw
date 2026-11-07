from django.urls import path

from . import views

urlpatterns = [
    path('', views.landing, name='landing'),
    path('home/', views.home, name='home'),
    path('profile/', views.profile, name='profile'),
    path('profile/children/add/', views.add_child, name='add_child'),
    path('profile/children/<int:pk>/remove/', views.remove_child, name='remove_child'),
]
