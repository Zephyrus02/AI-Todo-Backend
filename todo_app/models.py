from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
import uuid


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()
    name = models.CharField(max_length=255)
    usage_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'categories'
        unique_together = ['user_id', 'name']
        verbose_name_plural = 'Categories'
        managed = False

    def __str__(self):
        return f"{self.name} ({self.user_id})"


class Task(models.Model):
    PRIORITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
    ]
    
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('In Progress', 'In Progress'),
        ('Completed', 'Completed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category_id = models.UUIDField(null=True, blank=True)
    priority_score = models.IntegerField(null=True, blank=True)
    priority_label = models.CharField(
        max_length=10, 
        choices=PRIORITY_CHOICES,
        null=True,
        blank=True
    )
    deadline = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=15, 
        choices=STATUS_CHOICES, 
        default='Pending'
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'tasks'
        ordering = ['-created_at']
        managed = False

    def __str__(self):
        return f"{self.title} - {self.status}"

    @property
    def category(self):
        if self.category_id:
            try:
                return Category.objects.get(id=self.category_id)
            except Category.DoesNotExist:
                return None
        return None


class ContextEntry(models.Model):
    SOURCE_TYPE_CHOICES = [
        ('WhatsApp', 'WhatsApp'),
        ('Email', 'Email'),
        ('Note', 'Note'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField()
    content = models.TextField()
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPE_CHOICES)
    insights = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'context_entries'
        ordering = ['-created_at']
        verbose_name_plural = 'Context Entries'
        managed = False

    def __str__(self):
        return f"{self.source_type} - {self.content[:50]}..."