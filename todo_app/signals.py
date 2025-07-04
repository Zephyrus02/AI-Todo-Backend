from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache
from .models import Task, ContextEntry
import logging

def clear_task_caches(user_id):
    """Clears all task-related caches for a specific user."""
    if user_id:
        # Clear cache for the AI processing endpoint
        cache.delete(f"user_{user_id}_tasks_for_processing")
        
        # Clear all list view caches for tasks using a pattern
        list_pattern = f"user_{user_id}_task_list_*"
        # Check if the cache backend supports delete_pattern (for django-redis)
        if hasattr(cache, 'delete_pattern') and callable(getattr(cache, 'delete_pattern', None)):
            cache.delete_pattern(list_pattern)
            logging.info(f"Cleared task caches for user {user_id} (pattern: {list_pattern})")
        else:
            logging.warning("Cache backend does not support delete_pattern. Task list caches may not be fully cleared.")

def clear_context_caches(user_id):
    """Clears all context-related caches for a specific user."""
    if user_id:
        # Clear cache for the AI processing endpoint
        cache.delete(f"user_{user_id}_contexts_for_processing")
        
        # Clear all list view caches for contexts using a pattern
        list_pattern = f"user_{user_id}_context_list_*"
        # Check if the cache backend supports delete_pattern (for django-redis)
        if hasattr(cache, 'delete_pattern') and callable(getattr(cache, 'delete_pattern', None)):
            cache.delete_pattern(list_pattern)
            logging.info(f"Cleared context caches for user {user_id} (pattern: {list_pattern})")
        else:
            logging.warning("Cache backend does not support delete_pattern. Context list caches may not be fully cleared.")

@receiver(post_save, sender=Task)
def clear_task_cache_on_save(sender, instance, **kwargs):
    """Invalidate cache when a Task is saved."""
    clear_task_caches(instance.user_id)

@receiver(post_delete, sender=Task)
def clear_task_cache_on_delete(sender, instance, **kwargs):
    """Invalidate cache when a Task is deleted."""
    clear_task_caches(instance.user_id)

@receiver(post_save, sender=ContextEntry)
def clear_context_cache_on_save(sender, instance, **kwargs):
    """Invalidate cache when a ContextEntry is saved."""
    clear_context_caches(instance.user_id)

@receiver(post_delete, sender=ContextEntry)
def clear_context_cache_on_delete(sender, instance, **kwargs):
    """Invalidate cache when a ContextEntry is deleted."""
    clear_context_caches(instance.user_id)