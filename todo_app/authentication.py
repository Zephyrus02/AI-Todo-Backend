import jwt
import requests
from django.contrib.auth.models import User
from django.contrib.auth.backends import BaseBackend
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from django.conf import settings
from django.core.cache import cache
from supabase import create_client, Client
import json

class SupabaseTokenAuthentication(BaseAuthentication):
    def __init__(self):
        self.supabase: Client = create_client(
            settings.SUPABASE_URL, 
            settings.SUPABASE_ANON_KEY
        )
    
    def authenticate(self, request):
        auth_header = request.META.get('HTTP_AUTHORIZATION')
        if not auth_header or not auth_header.startswith('Bearer '):
            return None
        
        token = auth_header.split(' ')[1]
        
        try:
            # Verify token with Supabase client
            user_response = self.supabase.auth.get_user(token)
            
            if not user_response or not user_response.user:
                raise AuthenticationFailed('Invalid token')
            
            supabase_user = user_response.user
            
            # Get or create Django user based on Supabase user info
            user, created = User.objects.get_or_create(
                username=supabase_user.id,
                defaults={
                    'email': supabase_user.email,
                    'first_name': supabase_user.user_metadata.get('first_name', ''),
                    'last_name': supabase_user.user_metadata.get('last_name', ''),
                }
            )
            
            return (user, token)
            
        except Exception as e:
            raise AuthenticationFailed(f'Authentication failed: {str(e)}')

class SupabaseAuthBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        # This is for the Django admin/session authentication
        return None
    
    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None