from django.contrib.auth.models import AbstractUser
from django.db import models


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

    def __str__(self):
        return f'{self.parent} → {self.child}'
