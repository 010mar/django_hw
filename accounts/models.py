from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.urls import reverse


class User(AbstractUser):
    class Role(models.TextChoices):
        TEACHER = 'teacher', 'Учитель'
        STUDENT = 'student', 'Ученик'
        PARENT = 'parent', 'Родитель'

    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.STUDENT,
        verbose_name='Роль',
    )
    avatar = models.ImageField(
        upload_to='avatars/',
        blank=True,
        null=True,
        verbose_name='Аватар',
    )

    @property
    def avatar_url(self) -> str:
        if not self.avatar:
            return ''
        return reverse('protected_media', args=[self.avatar.name])

    @property
    def role_verbose(self) -> str:
        return self.get_role_display()

    @property
    def is_teacher(self) -> bool:
        return self.role == self.Role.TEACHER

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT

    @property
    def is_parent(self) -> bool:
        return self.role == self.Role.PARENT


class ParentLink(models.Model):
    parent = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='children',
        verbose_name='Родитель',
    )
    child = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='parent_links',
        verbose_name='Ребёнок',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('parent', 'child')
        verbose_name = 'Привязка родителя к ребёнку'
        verbose_name_plural = 'Привязки родителя к детям'

    def clean(self):
        super().clean()
        if not self.parent_id or not self.child_id:
            return
        errors = {}
        if self.parent_id == self.child_id:
            errors['child'] = 'Нельзя привязать пользователя к самому себе.'
        else:
            if self.parent.role != User.Role.PARENT:
                errors['parent'] = 'Пользователь должен иметь роль «Родитель».'
            if self.child.role != User.Role.STUDENT:
                errors['child'] = 'Пользователь должен иметь роль «Ученик».'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.parent} → {self.child}'
