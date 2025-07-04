from django.contrib import admin
from .models import Category, Task, ContextEntry


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'user_id', 'usage_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name', 'user_id']
    readonly_fields = ['id', 'created_at']
    ordering = ['-usage_count', 'name']


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ['title', 'user_id', 'status', 'priority_label', 'deadline', 'created_at']
    list_filter = ['status', 'priority_label', 'created_at']
    search_fields = ['title', 'description', 'user_id']
    readonly_fields = ['id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related()


@admin.register(ContextEntry)
class ContextEntryAdmin(admin.ModelAdmin):
    list_display = ['content_preview', 'user_id', 'source_type', 'created_at']
    list_filter = ['source_type', 'created_at']
    search_fields = ['content', 'user_id']
    readonly_fields = ['id', 'created_at']
    ordering = ['-created_at']
    
    @admin.display(description='Content Preview')
    def content_preview(self, obj):
        return obj.content[:50] + "..." if len(obj.content) > 50 else obj.content