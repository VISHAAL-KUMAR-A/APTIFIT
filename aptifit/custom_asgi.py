from fitness.new_consumers import WebConsumer
from django.urls import path
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
import os
import django

# Set Django settings module first
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aptifit.settings')
django.setup()

# Now import components

# Import the new consumer

# Define the ASGI application
application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        URLRouter([
            path('ws/<str:id>/', WebConsumer.as_asgi()),
            path('ws/', WebConsumer.as_asgi()),
        ])
    )
})
