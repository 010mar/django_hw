from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ParentLink, User


class ParentLinkInline(admin.TabularInline):
    model = ParentLink
    fk_name = 'parent'
    extra = 1
    autocomplete_fields = ('child',)
    verbose_name = 'Ребёнок'
    verbose_name_plural = 'Дети'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'child':
            kwargs['queryset'] = User.objects.filter(role=User.Role.STUDENT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Роль', {'fields': ('role',)}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        ('Роль', {'fields': ('role',)}),
    )
    inlines = (ParentLinkInline,)

    def get_inline_instances(self, request, obj=None):
        inlines = super().get_inline_instances(request, obj)
        if obj is None or obj.role != User.Role.PARENT:
            return [i for i in inlines if not isinstance(i, ParentLinkInline)]
        return inlines


@admin.register(ParentLink)
class ParentLinkAdmin(admin.ModelAdmin):
    list_display = ('parent', 'child', 'created_at')
    list_select_related = ('parent', 'child')
    search_fields = (
        'parent__username', 'parent__email', 'child__username', 'child__email',
    )
    autocomplete_fields = ('parent', 'child')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == 'parent':
            kwargs['queryset'] = User.objects.filter(role=User.Role.PARENT)
        elif db_field.name == 'child':
            kwargs['queryset'] = User.objects.filter(role=User.Role.STUDENT)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
