from channels.generic.websocket import AsyncWebsocketConsumer
import json
from channels.db import database_sync_to_async
import logging

logger = logging.getLogger(__name__)


class WebConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user_id = self.scope['url_route']['kwargs'].get('id')
        self.room_group_name = f"chat_user_{self.user_id}"

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Accept connection
        await self.accept()
        logger.info(f"WebSocket connected for user {self.user_id}")

    async def disconnect(self, close_code):
        # Leave room group
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )
        logger.info(f"WebSocket disconnected for user {self.user_id}")

    # Receive message from WebSocket
    async def receive(self, text_data):
        try:
            logger.info(f"Received message: {text_data}")
            data = json.loads(text_data)

            if data['type'] == 'message':
                message = data['message']
                receiver_id = data['to']

                # Save message to database
                await self.save_message(self.user_id, receiver_id, message)

                # Format timestamp
                from django.utils import timezone
                timestamp = timezone.now().isoformat()

                # Send message to room group
                await self.channel_layer.group_send(
                    f"chat_user_{receiver_id}",
                    {
                        'type': 'chat_message',
                        'message': message,
                        'sender_id': int(self.user_id),
                        'receiver_id': int(receiver_id),
                        'timestamp': timestamp,
                    }
                )

                # Also send to the sender's group
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': message,
                        'sender_id': int(self.user_id),
                        'receiver_id': int(receiver_id),
                        'timestamp': timestamp,
                    }
                )

        except Exception as e:
            logger.error(f"Error in receive: {str(e)}")

    # Receive message from room group
    async def chat_message(self, event):
        try:
            # Send message to WebSocket
            await self.send(text_data=json.dumps({
                'type': 'message',
                'message': event['message'],
                'sender_id': event['sender_id'],
                'receiver_id': event['receiver_id'],
                'timestamp': event['timestamp'],
            }))
            logger.info(f"Sent message to client: {event['message']}")
        except Exception as e:
            logger.error(f"Error in chat_message: {str(e)}")

    @database_sync_to_async
    def save_message(self, sender_id, receiver_id, message):
        from django.contrib.auth.models import User
        from fitness.models import CommunityMessage

        sender = User.objects.get(id=sender_id)
        receiver = User.objects.get(id=receiver_id)

        return CommunityMessage.objects.create(
            sender=sender,
            receiver=receiver,
            message=message
        )
