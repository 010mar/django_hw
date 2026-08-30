from django.urls import path

from . import views

urlpatterns = [
    path('banks/', views.bank_list, name='bank_list'),
    path('banks/new/', views.bank_create, name='bank_create'),
    path('banks/<int:pk>/', views.bank_detail, name='bank_detail'),
    path('banks/<int:pk>/edit/', views.bank_edit, name='bank_edit'),
    path('banks/<int:pk>/delete/', views.bank_delete, name='bank_delete'),
    path('banks/<int:pk>/topics/new/', views.topic_create, name='topic_create'),
    path('topics/<int:pk>/delete/', views.topic_delete, name='topic_delete'),
    path('tasks/', views.task_list, name='task_list'),
    path('tasks/new/', views.task_create, name='task_create'),
    path('tasks/<int:pk>/', views.task_detail, name='task_detail'),
    path('tasks/<int:pk>/edit/', views.task_edit, name='task_edit'),
    path('tasks/<int:pk>/delete/', views.task_delete, name='task_delete'),
    path('lessons/', views.lesson_list, name='lesson_list'),
    path('lessons/new/', views.lesson_create, name='lesson_create'),
    path('lessons/<int:pk>/', views.lesson_detail, name='lesson_detail'),
    path('lessons/<int:pk>/edit/', views.lesson_edit, name='lesson_edit'),
    path('lessons/<int:pk>/delete/', views.lesson_delete, name='lesson_delete'),
    path('lessons/<int:pk>/add_task/', views.lesson_add_task, name='lesson_add_task'),
    path('lessons/<int:pk>/remove_task/<int:task_id>/', views.lesson_remove_task, name='lesson_remove_task'),
]
