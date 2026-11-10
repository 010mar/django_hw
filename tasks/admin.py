from django.contrib import admin

from .models import (
    AnswerOption,
    Course,
    CourseModule,
    Lesson,
    LessonTask,
    Task,
    TaskAttachment,
    TaskBank,
    TaskBlock,
    TaskContext,
    TaskImage,
    TestCase,
    Topic,
)


class AnswerOptionInline(admin.TabularInline):
    model = AnswerOption
    extra = 1


class TaskBlockInline(admin.TabularInline):
    model = TaskBlock
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


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'created_at')
    search_fields = ('title', 'description')
    list_select_related = ('author',)


@admin.register(CourseModule)
class CourseModuleAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'start_date', 'order')
    search_fields = ('title', 'course__title')
    list_select_related = ('course',)


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
            'fields': ('title', 'body', 'type', 'difficulty', 'image', 'bank', 'topic', 'context', 'author'),
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
    inlines = [AnswerOptionInline, TaskBlockInline, TestCaseInline]


@admin.register(TaskBlock)
class TaskBlockAdmin(admin.ModelAdmin):
    list_display = ('task', 'kind', 'order')
    list_filter = ('kind',)
    search_fields = ('task__title', 'text', 'answers')
    list_select_related = ('task',)


@admin.register(TaskImage)
class TaskImageAdmin(admin.ModelAdmin):
    list_display = ('token', 'task', 'context', 'author', 'created_at')
    search_fields = ('token',)
    list_select_related = ('task', 'context', 'author')


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ('filename', 'task', 'context', 'created_at')
    search_fields = ('original_name', 'file')
    list_select_related = ('task', 'context')


@admin.register(TaskContext)
class TaskContextAdmin(admin.ModelAdmin):
    list_display = ('title', 'bank', 'author', 'task_count', 'created_at')
    search_fields = ('title', 'body')
    list_select_related = ('bank', 'author')

    @admin.display(description='Вопросов')
    def task_count(self, obj):
        return obj.task_count


@admin.register(Lesson)
class LessonAdmin(admin.ModelAdmin):
    list_display = ('title', 'author', 'task_count', 'created_at')
    search_fields = ('title', 'description')
    list_select_related = ('author',)
    inlines = [LessonTaskInline]

    @admin.display(description='Задач')
    def task_count(self, obj):
        return obj.entries.count()
