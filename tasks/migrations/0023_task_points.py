from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0022_symmetrize_related_tasks'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='points',
            field=models.PositiveIntegerField(
                default=1,
                help_text='Сколько баллов даёт задача',
                verbose_name='Баллы',
            ),
        ),
    ]
