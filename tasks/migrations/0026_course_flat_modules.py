from django.db import migrations, models


def enable_flat_modules_for_probniki(apps, schema_editor):
    Course = apps.get_model('tasks', 'Course')
    for course in Course.objects.all():
        title = (course.title or '').lower()
        if 'probnik' in title or 'пробник' in title:
            course.flat_modules = True
            course.save(update_fields=['flat_modules'])


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0025_course_exam_mode'),
    ]

    operations = [
        migrations.AddField(
            model_name='course',
            name='flat_modules',
            field=models.BooleanField(default=False, help_text='Не разделять модули и уроки: каждый модуль показывается одним уроком (например, для курса пробников)', verbose_name='Модуль = урок'),
        ),
        migrations.RunPython(
            enable_flat_modules_for_probniki,
            migrations.RunPython.noop,
        ),
    ]
