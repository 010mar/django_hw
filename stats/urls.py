from django.urls import path

from . import views

urlpatterns = [
    path('stats/my/', views.my_stats, name='my_stats'),
    path('stats/student/<int:pk>/', views.student_stats, name='student_stats'),
    path('stats/children/', views.parent_children, name='parent_children'),
    path('stats/class/<int:pk>/', views.class_stats, name='class_stats'),
]
