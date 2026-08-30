from django.contrib import admin

from .models import Assignment, ClassGroup, Submission


@admin.register(ClassGroup)
class ClassGroupAdmin(admin.ModelAdmin):
    list_display = ('title', 'teacher', 'created_at')
    filter_horizontal = ('students',)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'class_group', 'deadline', 'created_at')
    list_filter = ('class_group',)
    filter_horizontal = ('students', 'tasks')


@admin.register(Submission)
class SubmissionAdmin(admin.ModelAdmin):
    list_display = ('student', 'task', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('student__username', 'task__title')
