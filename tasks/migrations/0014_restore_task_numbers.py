from django.db import migrations


def restore_task_numbers(apps, schema_editor):
    Task = apps.get_model('tasks', 'Task')
    TaskBank = apps.get_model('tasks', 'TaskBank')
    prefixes = {
        bank.pk: (bank.prefix or '').strip() or str(bank.pk)
        for bank in TaskBank.objects.all()
    }
    for task in Task.objects.exclude(task_number='').select_related('topic'):
        if not task.topic_id:
            continue
        prefix = prefixes.get(task.topic.bank_id)
        if not prefix:
            continue
        marker = f'{prefix}_'
        if not task.task_number.startswith(marker):
            continue
        old_number = task.task_number
        new_number = old_number[len(marker):]
        task.task_number = new_number
        if task.title == old_number:
            task.title = new_number
        task.save(update_fields=['task_number', 'title'])


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0013_taskbank_prefix'),
    ]

    operations = [
        migrations.RunPython(restore_task_numbers, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name='taskbank',
            name='prefix',
        ),
    ]
