from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CategoryViewSet, TaskViewSet, ContextEntryViewSet, process_contexts_for_tasks

router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'tasks', TaskViewSet, basename='task')
router.register(r'context-entries', ContextEntryViewSet, basename='contextentry')

urlpatterns = [
    path('api/', include(router.urls)),
    # New endpoint for processing contexts
    path('api/process-contexts/<uuid:user_id>/', process_contexts_for_tasks, name='process-contexts'),
]