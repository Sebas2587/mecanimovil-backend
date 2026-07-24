from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .attachment_views import message_attachment_download
from .views import ConversationViewSet

router = DefaultRouter()
router.register(r'conversations', ConversationViewSet, basename='conversation')

urlpatterns = [
    path('messages/<int:message_id>/attachment/', message_attachment_download, name='chat-message-attachment'),
    path('', include(router.urls)),
]
