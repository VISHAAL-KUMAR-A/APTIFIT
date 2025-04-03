from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import (
    UserAttributeSimilarityValidator,
    MinimumLengthValidator,
    CommonPasswordValidator,
    NumericPasswordValidator
)
from django.contrib.auth import update_session_auth_hash, logout
from django.contrib.auth.forms import PasswordChangeForm
from django.core.mail import send_mail
from django.urls import reverse
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes
from django.http import JsonResponse
import os
import openai
import base64
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Remove the hardcoded API key and use environment variable instead
openai_api_key = os.environ.get("OPENAI_API_KEY")
openai.api_key = openai_api_key

# Create your views here.


def login_view(request):
    if request.method == 'POST':
        # Try to authenticate with username or email
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        # Check if the input is an email
        if '@' in username_or_email:
            try:
                user = User.objects.get(email=username_or_email)
                username = user.username
            except User.DoesNotExist:
                messages.error(request, 'Invalid credentials')
                return render(request, 'fitness/login.html')
        else:
            username = username_or_email

        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('index')
        messages.error(request, 'Invalid credentials')
    return render(request, 'fitness/login.html')


@login_required
def index(request):
    return render(request, 'fitness/index.html')


@login_required
def profile(request):
    return render(request, 'fitness/profile.html', {
        'user': request.user
    })


@login_required
def change_password(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            # Update the session to prevent the user from being logged out
            update_session_auth_hash(request, user)
            messages.success(
                request, 'Your password was successfully changed!')
            # First logout the user
            logout(request)
            # Then redirect to login page
            return redirect('login')
        else:
            # Add error messages for specific validation failures
            for error in form.errors.values():
                messages.error(request, error)
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'fitness/changepassword.html', {
        'form': form
    })


def forget_password(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        try:
            user = User.objects.get(email=email)
            # Generate password reset token
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            # Build password reset link
            reset_link = request.build_absolute_uri(
                reverse('password_reset_confirm', kwargs={
                        'uidb64': uid, 'token': token})
            )

            # Send email
            send_mail(
                'Password Reset Request',
                f'Click the following link to reset your password: {reset_link}',
                'vkthedon123@gmail.com',  # Your sender email
                [email],
                fail_silently=False,
            )
            messages.success(
                request, 'Password reset link has been sent to your email.')
            return redirect('login')
        except User.DoesNotExist:
            messages.error(request, 'No user found with this email address.')
    return render(request, 'fitness/forgetpassword.html')


def reset_password(request, uidb64, token):
    try:
        # Decode the user ID and get the user
        uid = urlsafe_base64_decode(uidb64).decode()
        user = User.objects.get(pk=uid)

        # Verify token is valid
        if not default_token_generator.check_token(user, token):
            messages.error(request, 'Invalid or expired password reset link.')
            return redirect('login')

        if request.method == 'POST':
            password1 = request.POST.get('new_password1')
            password2 = request.POST.get('new_password2')

            if password1 != password2:
                messages.error(request, 'Passwords do not match')
                return render(request, 'fitness/resetpassword.html')

            # Print out password errors for debugging
            password_errors = validate_password(password1, user)
            print("Password Errors:", password_errors)  # Add this line

            if password_errors:
                for error in password_errors:
                    messages.error(request, error)
                return render(request, 'fitness/resetpassword.html')

            # Set new password
            user.set_password(password1)
            user.save()
            messages.success(request, 'Your password was successfully reset!')
            return redirect('login')

        return render(request, 'fitness/resetpassword.html')

    except (TypeError, ValueError, User.DoesNotExist, OverflowError):
        messages.error(request, 'Invalid password reset link.')
        return redirect('login')


def logout_view(request):
    logout(request)
    return redirect('login')


def register_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password1')
        confirm_password = request.POST.get('password2')

        # Check if username or email already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists')
            return render(request, 'fitness/register.html')

        if User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists')
            return render(request, 'fitness/register.html')

        # Validate password
        password_errors = validate_password(password)
        if password_errors:
            for error in password_errors:
                messages.error(request, error)
            return render(request, 'fitness/register.html')

        # Check password match
        if password != confirm_password:
            messages.error(request, 'Passwords do not match')
            return render(request, 'fitness/register.html')

        # Create user
        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password
            )

            # Authenticate and login the user
            authenticated_user = authenticate(
                request, username=username, password=password)
            if authenticated_user:
                login(request, authenticated_user)
                return redirect('index')
            else:
                messages.error(request, 'Authentication failed')
                return render(request, 'fitness/register.html')

        except Exception as e:
            messages.error(request, f'Registration failed: {str(e)}')
            return render(request, 'fitness/register.html')

    return render(request, 'fitness/register.html')


def validate_password(password, user=None):
    errors = []
    validators = [
        UserAttributeSimilarityValidator(),
        MinimumLengthValidator(min_length=8),
        CommonPasswordValidator(),
        NumericPasswordValidator()
    ]

    for validator in validators:
        try:
            validator.validate(password, user)
        except Exception as e:
            errors.append(str(e))

    return errors


def ask_openapi(message):
    response = openai.Completion.create(
        model="text-davinci-003",
        prompt=message,
        max_tokens=150,
        n=1,
        stop=None,
        temperature=0.7,)
    answer = response.choices[0].text.strip()
    return answer


def chatbot(request):
    if request.method == 'POST':
        message = request.POST.get('message', '')
        image = request.FILES.get('image', None)

        # Define the specialized fitness assistant instructions
        system_message = """You are a specialized fitness and health assistant.
        Only answer questions related to health, exercise, nutrition, diet, and overall wellness.
        If a question is unrelated to these topics, politely explain that you're a fitness assistant
        and can only help with health, exercise, and nutrition-related topics.
        
        If you analyze an image showing food, provide nutritional insights.
        If you analyze an image showing exercise form, give feedback on proper technique.
        If you analyze an image showing a workout plan, provide constructive feedback.
        If you analyze an image of a fitness tracker or health metrics, interpret the data.
        
        Keep your answers informative, encouraging, and science-based."""

        try:
            # Initialize the OpenAI client
            client = openai.OpenAI(api_key=openai_api_key)

            # Prepare messages list
            messages = [{"role": "system", "content": system_message}]

            # If there's an image, convert it to base64 and add it to the messages
            if image:
                # Read the image data
                image_data = image.read()
                # Convert to base64
                base64_image = base64.b64encode(image_data).decode('utf-8')

                # Create content list with text and image
                content = [
                    {"type": "text", "text": message if message else "Please analyze this image related to fitness or health."}
                ]

                # Add the image content
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/{image.content_type};base64,{base64_image}"
                    }
                })

                # Add to messages
                messages.append({"role": "user", "content": content})
            else:
                # Text-only message
                messages.append({"role": "user", "content": message})

            # Generate response using GPT-4 Vision model - updated to use the current model
            response = client.chat.completions.create(
                model="gpt-4o",  # Updated to the current model that supports vision
                messages=messages,
                temperature=0.7,
                max_tokens=500,
            )

            # Extract the response content
            bot_response = response.choices[0].message.content

            # Return the response as JSON
            return JsonResponse({'message': message, 'response': bot_response})

        except Exception as e:
            # Handle any errors
            print(f"Error calling OpenAI API: {str(e)}")
            return JsonResponse({
                'message': message,
                'response': f"Sorry, I'm having trouble analyzing the image or processing your request. Error: {str(e)}"
            })

    return render(request, 'fitness/chatbot.html')
