from django.utils import translation
from django.utils.deprecation import MiddlewareMixin


class UserLanguageMiddleware(MiddlewareMixin):
    """Middleware to set the language based on user preference."""

    def process_request(self, request):
        # Check if user attribute exists and is authenticated
        if hasattr(request, 'user') and request.user.is_authenticated:
            try:
                # Get user's language preference from their profile
                user_language = request.user.userprofile.language
                if user_language:
                    translation.activate(user_language)
                    request.LANGUAGE_CODE = user_language
            except Exception:
                pass
        return None
