from django.urls import path

from . import views

urlpatterns = [
    path('classes/', views.class_list, name='class_list'),
    path('classes/new/', views.class_create, name='class_create'),
    path('classes/<int:pk>/', views.class_detail, name='class_detail'),
    path('classes/<int:pk>/delete/', views.class_delete, name='class_delete'),
    path('assignments/', views.assignment_list, name='assignment_list'),
    path('assignments/new/', views.assignment_create, name='assignment_create'),
    path('assignments/<int:pk>/', views.assignment_detail, name='assignment_detail'),
    path('assignments/<int:pk>/delete/', views.assignment_delete, name='assignment_delete'),
    path('assignments/<int:pk>/grade/', views.assignment_grade, name='assignment_grade'),
    path('submissions/<int:submission_id>/grade/', views.grade_submission, name='grade_submission'),
    path('my/', views.my_assignments, name='my_assignments'),
    path('my/<int:pk>/', views.assignment_solve, name='assignment_solve'),
    path('my/<int:assignment_id>/<int:task_id>/', views.solve_task, name='solve_task'),
]
