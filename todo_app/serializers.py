from rest_framework import serializers
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from .models import Category, Task, ContextEntry
import uuid
import requests
import json
import logging
import re


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'date_joined']
        read_only_fields = ['id', 'username', 'date_joined']


class CategorySerializer(serializers.ModelSerializer):
    task_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'usage_count', 'task_count', 'created_at']
        read_only_fields = ['id', 'usage_count', 'created_at']

    def get_task_count(self, obj):
        return Task.objects.filter(category_id=obj.id).count()

    def create(self, validated_data):
        # Use the Supabase user ID (stored as username)
        validated_data['user_id'] = uuid.UUID(self.context['request'].user.username)
        return super().create(validated_data)


class TaskSerializer(serializers.ModelSerializer):
    category_name = serializers.SerializerMethodField()
    category = serializers.CharField(allow_null=True, required=False)

    class Meta:
        model = Task
        fields = [
            'id', 'title', 'description', 'category', 'category_name',
            'priority_score', 'priority_label', 'deadline', 'status',
            'created_at', 'updated_at'
        ]
        # priority_score is now read-only from the user's perspective
        read_only_fields = ['id', 'created_at', 'updated_at', 'category_name', 'priority_score']

    def get_category_name(self, obj):
        if obj.category_id:
            try:
                category = Category.objects.get(id=obj.category_id)
                return category.name
            except Category.DoesNotExist:
                return None
        return None

    def _get_user_id(self):
        """Helper to get user_id from request or directly from context."""
        if 'user_id' in self.context:
            return self.context['user_id']
        if 'request' in self.context:
            return uuid.UUID(self.context['request'].user.username)
        raise ValueError("Could not determine user_id from serializer context.")

    def _calculate_priority_score(self, task_data):
        """
        Calls the local LM Studio model to calculate a priority score.
        """
        base_url = settings.LMSTUDIO_API_BASE_URL
        api_url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {"Content-Type": "application/json"}

        # --- Fetch existing tasks for context ---
        user_id = self._get_user_id()
        existing_tasks = Task.objects.filter(
            user_id=user_id, 
            status__in=['Pending', 'In Progress']
        ).order_by('-priority_score')[:10]

        existing_tasks_str = "The user has no other active tasks."
        if existing_tasks:
            task_list = []
            for task in existing_tasks:
                task_list.append(f"- Title: \"{task.title}\", Priority: {task.priority_label}, Current Score: {task.priority_score}")
            existing_tasks_str = "\n".join(task_list)

        # --- A more direct, forceful prompt for JSON output ---
        prompt = f"""
        Analyze the `new_task` in the context of the `existing_tasks`.

        **Existing Tasks:**
        {existing_tasks_str}

        **New Task:**
        - Title: {task_data.get('title')}
        - Description: {task_data.get('description', 'No description.')}
        - User-Assigned Priority: {task_data.get('priority_label', 'Not set.')}
        - Deadline: {task_data.get('deadline', 'No deadline.')}

        Based on this analysis, provide a numerical priority score from 1 to 100 for the new task.
        Your response MUST be a JSON object containing a single key "score". Do not include any other text, explanation, or markdown.

        Example response:
        {{"score": 92}}
        
        Ensure that the response is strictly a JSON object with no additional text.
        If you cannot determine an appropriate score based on the provided information, respond with a score of 50 for medium priority tasks, 85 for high priority tasks, and 20 for low priority tasks.
        """

        payload = {
            "model": "local-model",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,  # Keep temperature low for factual responses
            "max_tokens": 256,   # Increase to prevent the response from being cut off
        }

        try:
            logging.info(f"Attempting to call LM Studio at: {api_url}")
            response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=20)
            response.raise_for_status()
            
            content_str = response.json()['choices'][0]['message']['content']
            logging.debug(f"LLM Raw Response: {content_str}")

            # --- Robust Parsing Logic ---
            try:
                # Find the JSON object within the string, even if there's extra text
                json_match = re.search(r'\{.*\}', content_str, re.DOTALL)
                if not json_match:
                    raise ValueError("No JSON object found in the response.")
                
                score_data = json.loads(json_match.group(0))
                return int(score_data['score'])
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                logging.warning("Failed to parse LLM response as JSON, attempting regex fallback.")
                match = re.search(r'\d+', content_str)
                if match:
                    return int(match.group(0))
                raise ValueError("Could not extract a score from the LLM response.")

        except (requests.exceptions.RequestException, KeyError, ValueError, IndexError) as e:
            logging.error(f"LM Studio call failed or parsing failed: {e}")
            priority_map = {'High': 85, 'Medium': 50, 'Low': 15}
            return priority_map.get(task_data.get('priority_label'), 50)


    def create(self, validated_data):
        # User can no longer set priority_score directly
        validated_data.pop('priority_score', None)

        # Calculate priority score using the LLM
        calculated_score = self._calculate_priority_score(validated_data)
        validated_data['priority_score'] = calculated_score

        # Extract category name from validated data
        category_name = validated_data.pop('category', None)
        
        # Use the Supabase user ID from context
        user_id = self._get_user_id()
        validated_data['user_id'] = user_id
        
        # Handle category creation/lookup
        if category_name:
            category, created = Category.objects.get_or_create(
                user_id=user_id,
                name=category_name,
                defaults={'usage_count': 0}
            )
            # Increment usage count if category already exists
            if not created:
                category.usage_count += 1
                category.save()
            else:
                # Set initial usage count for new category
                category.usage_count = 1
                category.save()
            
            validated_data['category_id'] = category.id
        
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Extract category name from validated data
        category_name = validated_data.pop('category', None)
        
        # Handle category update
        if category_name is not None:
            user_id = uuid.UUID(self.context['request'].user.username)
            
            if category_name == '':
                # Empty string means remove category
                instance.category_id = None
            else:
                category, created = Category.objects.get_or_create(
                    user_id=user_id,
                    name=category_name,
                    defaults={'usage_count': 0}
                )
                # Increment usage count
                if not created:
                    category.usage_count += 1
                    category.save()
                else:
                    category.usage_count = 1
                    category.save()
                
                instance.category_id = category.id
        
        return super().update(instance, validated_data)

    def validate_category(self, value):
        if value and len(value.strip()) == 0:
            return None  # Treat empty strings as None
        return value


class ContextEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ContextEntry
        fields = ['id', 'content', 'source_type', 'insights', 'created_at']
        read_only_fields = ['id', 'created_at']

    def create(self, validated_data):
        # Use the Supabase user ID (stored as username)
        validated_data['user_id'] = uuid.UUID(self.context['request'].user.username)
        return super().create(validated_data)