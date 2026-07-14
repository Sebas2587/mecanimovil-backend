from django.urls import path

from . import oauth_views

urlpatterns = [
    path('ml/oauth/authorize/', oauth_views.ml_oauth_authorize, name='ml-oauth-authorize'),
    path('ml/oauth/callback/', oauth_views.ml_oauth_callback, name='ml-oauth-callback'),
    path('ml/oauth/status/', oauth_views.ml_oauth_status, name='ml-oauth-status'),
]
