from django.db import migrations


def symmetrize_related_tasks(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    through = Task.related_tasks.through
    rows = set(through.objects.values_list('from_task_id', 'to_task_id'))
    missing = [
        through(from_task_id=to_id, to_task_id=from_id)
        for from_id, to_id in rows
        if from_id != to_id and (to_id, from_id) not in rows
    ]
    if missing:
        through.objects.bulk_create(missing, ignore_conflicts=True)


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0021_remove_task_context_remove_taskattachment_context_and_more'),
    ]

    operations = [
        migrations.RunPython(symmetrize_related_tasks, migrations.RunPython.noop),
    ]
