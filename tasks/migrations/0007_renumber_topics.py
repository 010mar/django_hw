from django.db import migrations


def renumber(apps, schema_editor):
    Topic = apps.get_model('tasks', 'Topic')
    Task = apps.get_model('tasks', 'Task')
    bank_ids = list(Topic.objects.values_list('bank_id', flat=True).distinct())
    for bank_id in bank_ids:
        topics = list(
            Topic.objects.filter(bank_id=bank_id).order_by('order', 'created_at', 'pk')
        )
        old_orders = {}
        for index, topic in enumerate(topics, start=1):
            old_orders[topic.pk] = topic.order
            if topic.order != index:
                topic.order = index
                topic.save(update_fields=['order'])
        for task in Task.objects.filter(topic__bank_id=bank_id).exclude(task_number=''):
            old_order = old_orders.get(task.topic_id)
            if old_order is None:
                continue
            old_prefix = f'{old_order}_'
            if not task.task_number.startswith(old_prefix):
                continue
            new_number = f'{task.topic.order}_{task.task_number[len(old_prefix):]}'
            if task.title == task.task_number:
                task.title = new_number
            task.task_number = new_number
            task.save(update_fields=['task_number', 'title'])


def reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0006_taskimage'),
    ]

    operations = [
        migrations.RunPython(renumber, reverse),
    ]
