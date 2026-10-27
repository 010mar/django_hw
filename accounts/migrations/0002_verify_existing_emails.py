from django.conf import settings
from django.db import migrations


def verify_existing_emails(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    EmailAddress = apps.get_model('account', 'EmailAddress')

    EmailAddress.objects.filter(verified=False).update(verified=True)

    for user in User.objects.exclude(email='').iterator():
        addresses = EmailAddress.objects.filter(user_id=user.pk)
        if addresses.exists():
            if not addresses.filter(primary=True).exists():
                address = addresses.order_by('id').first()
                address.primary = True
                address.save(update_fields=['primary'])
            continue
        if EmailAddress.objects.filter(email__iexact=user.email).exists():
            continue
        EmailAddress.objects.create(
            user_id=user.pk,
            email=user.email.lower(),
            verified=True,
            primary=True,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('account', '0009_emailaddress_unique_primary_email'),
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(verify_existing_emails, migrations.RunPython.noop),
    ]
