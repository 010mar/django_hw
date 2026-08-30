from django.contrib import admin

from .models import AnswerOption, Lesson, LessonTask, Task, TaskBank, TestCase, Topic


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 1


class TestCaseInline(admin.TabularInline):
    model = TestCase
    extra = 1


class LessonTaskInline(admin.TabularInline):
    model = LessonTask
    extra = 1


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 1


@admin.register(TaskBank)
class TaskBankAdmin(admin.ModelAdmin):
    list_display = ('name', 'author', 'topic_count', 'task_count', 'created_at')
    search_fields = ('name', 'description')
    list_select_related = ('author',)
    inlines = [TopicInline]

    @admin.display(description='Тем')
    def topic_count(self, obj):
        return obj.topics.count()

    @admin.display(description='Задач')
    def task_count(self, obj):
        return obj.task_count


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'bank', 'task_count', 'order')
    search_fields = ('name', 'bank__name')
    list_select_related = ('bank',)

    @admin.display(description='Задач')
    def task_count(self, obj):
        return obj.tasks.count()


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ('title', 'bank', 'topic', 'type', 'difficulty', 'author', 'created_at')
    list_filter = ('type', 'difficulty', 'language')
    search_fields = ('title', 'body')
    list_select_related = ('author', 'bank', 'topic')
    fieldsets = (
        (None, {
            'fields': ('title', 'body', 'type', 'difficulty', 'image', 'bank', 'topic', 'author'),
        }),
        ('Текстовая задача', {
            'fields': ('answer_mode', 'correct_answer'),
            'classes': ('collapse',),
        }),
        ('Программирование', {
            'fields': ('language', 'time_limit_ms', 'memory_limit_mb'),
            'classes': ('collapse',),
        }),
    )
    inlines = [AnswerOptionInline, TestCaseInline]


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'task_count', 'created_at')
    search_fields = ('title', 'description')
    list_select_related = ('author',)
    inlines = [LessonTaskInline]

    @admin.display(description='Задач')
    def task_count(self, obj):
        return obj.entries.count()
