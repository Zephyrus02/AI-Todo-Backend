from rest_framework import viewsets, filters, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.request import Request
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, QuerySet
from .models import Category, Task, ContextEntry
from .serializers import CategorySerializer, TaskSerializer, ContextEntrySerializer
import uuid
import requests
import json
import logging
import re
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache


class CategoryViewSet(viewsets.ModelViewSet):
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['name', 'usage_count', 'created_at']
    ordering = ['-usage_count', 'name']

    def get_queryset(self) -> QuerySet[Category]:
        user_id = uuid.UUID(self.request.user.username)
        return Category.objects.filter(user_id=user_id)


class TaskViewSet(viewsets.ModelViewSet):
    serializer_class = TaskSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'priority_label', 'category_id']
    search_fields = ['title', 'description']
    ordering_fields = ['created_at', 'updated_at', 'deadline', 'priority_score']
    ordering = ['-created_at']

    def get_queryset(self) -> QuerySet[Task]:
        user_id = uuid.UUID(self.request.user.username)
        queryset = Task.objects.filter(user_id=user_id)
        
        # Filter by status if provided
        status_filter = self.request.GET.get('status')
        if status_filter:
            queryset = queryset.filter(status=status_filter)
            
        # Filter by priority if provided
        priority_filter = self.request.GET.get('priority')
        if priority_filter:
            queryset = queryset.filter(priority_label=priority_filter)
            
        return queryset

    def list(self, request, *args, **kwargs):
        user_id = uuid.UUID(self.request.user.username)
        
        # Create a unique cache key based on user and query params
        query_params = request.query_params.dict()
        sorted_params = sorted(query_params.items())
        params_str = '&'.join([f"{k}={v}" for k, v in sorted_params])
        cache_key = f"user_{user_id}_task_list_{params_str}"

        # Try to fetch from cache
        cached_response = cache.get(cache_key)
        if cached_response:
            logging.info(f"CACHE HIT for task list: {cache_key}")
            return Response(cached_response)

        logging.info(f"CACHE MISS for task list: {cache_key}. Querying database.")
        
        # If cache miss, proceed as normal
        response = super().list(request, *args, **kwargs)
        
        # Cache the successful response data
        if response.status_code == 200:
            cache.set(cache_key, response.data, timeout=3600) # Cache for 1 hour

        return response

    @action(detail=True, methods=['patch'])
    def update_status(self, request, pk=None):
        task = self.get_object()
        new_status = request.data.get('status')
        
        if new_status in ['Pending', 'In Progress', 'Completed']:
            task.status = new_status
            task.save()
            return Response({'status': 'Task status updated'})
        else:
            return Response(
                {'error': 'Invalid status'}, 
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        user_id = uuid.UUID(request.user.username)
        user_tasks = Task.objects.filter(user_id=user_id)
        stats = {
            'total_tasks': user_tasks.count(),
            'pending_tasks': user_tasks.filter(status='Pending').count(),
            'in_progress_tasks': user_tasks.filter(status='In Progress').count(),
            'completed_tasks': user_tasks.filter(status='Completed').count(),
            'high_priority_tasks': user_tasks.filter(priority_label='High').count(),
        }
        return Response(stats)


class ContextEntryViewSet(viewsets.ModelViewSet):
    serializer_class = ContextEntrySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['source_type']
    search_fields = ['content']
    ordering_fields = ['created_at']
    ordering = ['-created_at']

    def get_queryset(self) -> QuerySet[ContextEntry]:
        user_id = uuid.UUID(self.request.user.username)
        return ContextEntry.objects.filter(user_id=user_id)

    def list(self, request, *args, **kwargs):
        user_id = uuid.UUID(self.request.user.username)
        
        # Create a unique cache key based on user and query params
        query_params = request.query_params.dict()
        sorted_params = sorted(query_params.items())
        params_str = '&'.join([f"{k}={v}" for k, v in sorted_params])
        cache_key = f"user_{user_id}_context_list_{params_str}"

        # Try to fetch from cache
        cached_response = cache.get(cache_key)
        if cached_response:
            logging.info(f"CACHE HIT for context list: {cache_key}")
            return Response(cached_response)

        logging.info(f"CACHE MISS for context list: {cache_key}. Querying database.")
        
        # If cache miss, proceed as normal
        response = super().list(request, *args, **kwargs)
        
        # Cache the successful response data
        if response.status_code == 200:
            cache.set(cache_key, response.data, timeout=3600) # Cache for 1 hour

        return response


@api_view(['POST'])
@permission_classes([AllowAny])  # This makes the endpoint public
def process_contexts_for_tasks(request, user_id):
    """
    Analyzes a user's contexts against their existing tasks and creates new tasks
    for actionable items that are not already covered.
    """
    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        return Response({"error": "Invalid user ID format."}, status=status.HTTP_400_BAD_REQUEST)

    # --- Caching Logic ---
    tasks_cache_key = f"user_{user_uuid}_tasks_for_processing"
    contexts_cache_key = f"user_{user_uuid}_contexts_for_processing"
    
    # 1. Try to fetch serialized data from Redis cache
    tasks_str = cache.get(tasks_cache_key)
    contexts_str = cache.get(contexts_cache_key)

    # If cache miss, query DB and set cache
    if not tasks_str:
        logging.info(f"CACHE MISS for tasks: {tasks_cache_key}. Querying database.")
        existing_tasks = Task.objects.filter(user_id=user_uuid, status__in=['Pending', 'In Progress'])
        tasks_str = json.dumps([
            {"title": task.title, "description": task.description, "status": task.status, "deadline": task.deadline.isoformat() if task.deadline else None}
            for task in existing_tasks
        ], indent=2)
        cache.set(tasks_cache_key, tasks_str, timeout=3600) # Cache for 1 hour
    else:
        logging.info(f"CACHE HIT for tasks: {tasks_cache_key}. Using cached data.")

    if not contexts_str:
        logging.info(f"CACHE MISS for contexts: {contexts_cache_key}. Querying database.")
        all_contexts = ContextEntry.objects.filter(user_id=user_uuid).order_by('-created_at')[:20]
        contexts_str = json.dumps([
            {"content": ctx.content, "source_type": ctx.source_type, "insights": ctx.insights, "recorded_at": ctx.created_at.isoformat()}
            for ctx in all_contexts
        ], indent=2)
        cache.set(contexts_cache_key, contexts_str, timeout=3600) # Cache for 1 hour
    else:
        logging.info(f"CACHE HIT for contexts: {contexts_cache_key}. Using cached data.")

    # 2. Construct a more advanced prompt for the LLM
    prompt = f"""
You are a hyper-intelligent and meticulous task creation assistant. Your purpose is to analyze a user's unstructured notes and messages (`Contexts`) and compare them against their structured `Existing Tasks` to identify and create new, actionable tasks. You must be very careful to avoid creating duplicate or outdated tasks.

Today's Date: {timezone.now().strftime('%A, %d/%m/%Y')}

**Primary Directive:**
Analyze the `Contexts to Analyze` section. For each context, decide if a new task should be created. A new task is ONLY created if it's a new, actionable item that is NOT already covered by an `Existing Task` (regardless of its status) and is NOT for an event that has already passed.

**Rules for Task Creation:**
1.  **Check for Duplicates (Crucial):** Before creating a task, meticulously check the `Existing Tasks`. If a task with a similar title or description already exists (even if 'Completed'), do NOT create a new one.
2.  **Analyze Dates Carefully:** Use "Today's Date" as a reference. Do not create tasks for events that are clearly in the past.
3.  **Infer All Fields:** For each new task, you must infer a `title`, `description`, `category` (e.g., Work, Personal, Health), `priority_label` ('High', 'Medium', or 'Low'), and a `deadline`.
4.  **Calculate Deadlines (Crucial):**
    -   If a relative date is mentioned (e.g., "next Friday", "tomorrow"), calculate the absolute date and format it as 'YYYY-MM-DDTHH:MM:SSZ'.
    -   **Day of the Week Logic:** When a day of the week (e.g., "Saturday", "Monday") is mentioned without the word "next", assume it refers to the **nearest upcoming** instance of that day.
    -   **Example:** If today is Friday, July 4th, a task for "Saturday" should have a deadline of Saturday, July 5th. A task for "next Friday" would be July 11th.
    -   If no time is mentioned, use a sensible default like '17:00:00'. If no deadline is implied, the deadline must be `null`.
5.  **Strict JSON Output:** Your entire response MUST be a single JSON array `[]`. The array will contain zero or more task objects. Do NOT include any text, explanation, or markdown before or after the JSON array.

---
**Input Data:**

**Existing Tasks:**
```json
{tasks_str}
```

**Contexts to Analyze:**
```json
{contexts_str}
```

---
**Your JSON Response (must be only the array):**
"""

    # 3. Call the LM Studio model
    try:
        base_url = settings.LMSTUDIO_API_BASE_URL
        api_url = f"{base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 1024, # Allow for multiple task objects
        }
        response = requests.post(api_url, headers={"Content-Type": "application/json"}, data=json.dumps(payload), timeout=45)
        response.raise_for_status()
        content_str = response.json()['choices'][0]['message']['content']
        logging.debug(f"LLM Raw Response for Task Generation: {content_str}")

        # Extract the JSON array from the response
        json_match = re.search(r'\[.*\]', content_str, re.DOTALL)
        if not json_match:
            return Response({"created_count": 0, "details": "No new tasks suggested by AI."}, status=status.HTTP_200_OK)
        
        suggested_tasks = json.loads(json_match.group(0))

    except Exception as e:
        logging.error(f"Failed to process contexts with AI: {e}")
        return Response({"error": "Failed to communicate with the AI model."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # 4. Create tasks from the AI's suggestions
    created_tasks_info = []
    created_count = 0
    for task_data in suggested_tasks:
        # The TaskSerializer will handle priority score calculation
        serializer = TaskSerializer(data=task_data, context={'user_id': user_uuid})
        if serializer.is_valid():
            serializer.save()
            created_tasks_info.append(serializer.data)
            created_count += 1
        else:
            logging.warning(f"AI suggested an invalid task: {serializer.errors}")

    return Response({
        "created_count": created_count,
        "created_tasks": created_tasks_info
    }, status=status.HTTP_201_CREATED)