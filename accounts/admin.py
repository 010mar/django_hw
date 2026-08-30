from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ParentLink, User


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


@admin.register(ParentLink)
class ParentLinkAdmin(admin.ModelAdmin):
    list_display = ('parent', 'child', 'created_at')
    search_fields = ('parent__username', 'parent__email', 'child__username', 'child__email')
