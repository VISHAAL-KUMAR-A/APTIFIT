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
from fitness.models import DietPlan, DailyDietPlan, ExercisePlan, ExerciseDay, Exercise, ExerciseTip, ExercisePrecaution, HealthData, CommunityMessage
import re
from django.db.models import Q
from django.conf import settings
import json
import requests
from django.views.decorators.http import require_POST
import time
import logging
import urllib3
import certifi

# Disable SSL verification warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)

# Create your views here.

load_dotenv()
openai.api_key = os.environ.get("OPENAI_API_KEY")


def add_notification(request, message, category="info"):
    """
    Add a notification to the session
    """
    import datetime

    if 'notifications' not in request.session:
        request.session['notifications'] = []

    # Add the new notification
    request.session['notifications'].append({
        'message': message,
        'category': category,  # info, success, warning, error
        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'read': False
    })

    # Limit to the last 5 notifications
    if len(request.session['notifications']) > 5:
        request.session['notifications'] = request.session['notifications'][-5:]

    request.session.modified = True


def login_view(request):
    if request.method == 'POST':
        username_or_email = request.POST.get('username')
        password = request.POST.get('password')

        if not username_or_email or not password:
            messages.error(request, 'Please fill in all fields')
            return render(request, 'fitness/login.html')

        try:
            # First try to get user by email
            if '@' in username_or_email:
                try:
                    user = User.objects.get(email=username_or_email)
                    username = user.username
                except User.DoesNotExist:
                    messages.error(
                        request, 'No user found with this email address')
                    return render(request, 'fitness/login.html')
            else:
                username = username_or_email

            # Try to authenticate
            user = authenticate(request, username=username, password=password)

            if user is not None:
                if user.is_active:
                    login(request, user)
                    messages.success(request, 'Successfully logged in!')
                    return redirect('index')
                else:
                    messages.error(request, 'Your account is disabled')
            else:
                messages.error(request, 'Invalid password')

        except Exception as e:
            print(f"Login error: {str(e)}")  # For debugging
            messages.error(request, 'An error occurred during login')

    return render(request, 'fitness/login.html')


@login_required
def index(request):
    # Get the day parameter from the URL, default to current day
    import datetime
    day_param = request.GET.get('day')

    if day_param:
        current_day = day_param.lower()
    else:
        current_day = datetime.datetime.now().strftime('%A').lower()

    # Check if the user has a diet plan
    try:
        diet_plan = DietPlan.objects.get(user=request.user)
        # Get the diet plan for the current day
        daily_plan = diet_plan.get_day_plan(current_day)
    except DietPlan.DoesNotExist:
        diet_plan = None
        daily_plan = None

    # Get user profile data for stats
    user_profile = request.user.userprofile
    bmi = user_profile.bmi
    body_fat = user_profile.body_fat

    # Get daily calorie needs from user profile
    daily_calories = user_profile.daily_calorie_needs

    # Check for user notification preferences
    notification_preference = request.user.userprofile.notification_preference

    diet_notification = None
    exercise_notification = None

    if notification_preference == 'daily':
        # Get current day of week
        import datetime
        current_weekday = datetime.datetime.now().strftime('%A').lower()

        # Diet notification (this is likely what's already there)
        diet_notification = f"Remember to follow your {current_day} diet plan!"

        # Exercise notification - completely separate from diet notification
        if hasattr(request.user, 'exerciseplan'):
            exercise_plan = request.user.exerciseplan
            today_exercise = None

            # Find if there's an exercise scheduled for today
            for day in exercise_plan.days.all():
                if day.day.lower() == current_weekday:
                    today_exercise = day
                    break

            if today_exercise:
                exercise_notification = {
                    'message': f"Don't forget today's {today_exercise.focus} workout! ({today_exercise.duration})",
                    'timestamp': 'Today'
                }
            else:
                exercise_notification = {
                    'message': "Remember to check your exercise plan for today!",
                    'timestamp': 'Today'
                }

    # Get notifications from session
    notifications = request.session.get('notifications', [])
    unread_notifications = [
        n for n in notifications if not n.get('read', False)]
    has_unread = len(unread_notifications) > 0

    # Mark all as read when viewing the page
    if has_unread:
        for notification in notifications:
            notification['read'] = True
        request.session.modified = True

    # Add notifications to context
    context = {
        'diet_plan': diet_plan,
        'daily_plan': daily_plan,
        'current_day': current_day.title(),  # Capitalize for display
        'days_of_week': DailyDietPlan.DAYS_OF_WEEK,
        'bmi': bmi,
        'bmi_category': user_profile.bmi_category,
        'body_fat': body_fat,
        'body_fat_category': user_profile.body_fat_category,
        'daily_calories': daily_calories,
        'diet_notification': diet_notification,
        'exercise_notification': exercise_notification,
        'notification_preference': notification_preference,
        'notifications': notifications,
    }

    # Update notification count logic
    has_notifications = diet_notification is not None or exercise_notification is not None
    context['has_notifications'] = has_notifications

    if notifications:
        context['notification_count'] = len(
            notifications) + (1 if exercise_notification else 0)
    elif has_notifications:
        context['notification_count'] = (
            1 if diet_notification else 0) + (1 if exercise_notification else 0)

    return render(request, 'fitness/index.html', context)


@login_required
def profile(request):
    # Get user profile data
    user_profile = request.user.userprofile

    # Check if user has entered basic fitness data
    user_has_data = bool(
        user_profile.height and user_profile.weight and user_profile.sex and user_profile.age)
    missing_fields = []

    if not user_profile.height:
        missing_fields.append("height")
    if not user_profile.weight:
        missing_fields.append("weight")
    if not user_profile.sex:
        missing_fields.append("sex")
    if not user_profile.age:
        missing_fields.append("age")

    missing_fields_message = None
    if missing_fields:
        missing_fields_message = f"Please complete your profile by filling in: {', '.join(missing_fields)}"

    context = {
        'user': request.user,
        'user_has_data': user_has_data,
        'missing_fields': missing_fields,
        'missing_fields_message': missing_fields_message,
        'height': user_profile.height,
        'weight': user_profile.weight,
        'sex': user_profile.sex,
        'age': user_profile.age,
        'bmi': user_profile.bmi,
        'bmi_category': user_profile.bmi_category,
        'body_fat': user_profile.body_fat,
        'body_fat_category': user_profile.body_fat_category,
        'notification_preference': user_profile.notification_preference,
        # Add new fields to context
        'country': user_profile.country,
        'state': user_profile.state,
        'language': user_profile.language,
        'ethnic_group': user_profile.ethnic_group,
        'diet_preference': user_profile.diet_preference,
    }

    return render(request, 'fitness/profile.html', context)


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
    # Clear session data
    request.session.flush()
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


@login_required
def chatbot(request):
    # Import the messages framework
    from django.contrib import messages

    # Check if user profile is complete
    user_profile = request.user.userprofile
    profile_complete = bool(
        user_profile.height and
        user_profile.weight and
        user_profile.sex and
        user_profile.age
    )

    # If profile is incomplete, redirect to profile page with a message
    if not profile_complete:
        messages.warning(
            request,
            "Please complete your profile before using the chatbot. We need your height, weight, sex, and age to provide accurate fitness and diet recommendations."
        )
        return redirect('profile')

    if request.method == 'POST':
        message = request.POST.get('message', '')
        image = request.FILES.get('image', None)

        # Check if user is asking for a diet plan
        diet_plan_triggers = [
            'diet plan', 'diet', 'meal plan', 'nutrition plan',
            'eating plan', 'food plan', 'generate diet', 'create diet'
        ]

        is_diet_plan_request = any(trigger in message.lower()
                                   for trigger in diet_plan_triggers)

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
            client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

            # Prepare messages list
            messages = [{"role": "system", "content": system_message}]

            # If it's a diet plan request, include user profile data
            if is_diet_plan_request:
                user_profile = request.user.userprofile

                # Only proceed if user has completed their profile
                if user_profile.height and user_profile.weight and user_profile.sex and user_profile.age:
                    # Get daily calorie needs
                    daily_calories = user_profile.daily_calorie_needs or "Not calculated"

                    # Add location, ethnic group, and dietary preference data
                    location_data = {}
                    if user_profile.country:
                        location_data["country"] = user_profile.country
                    if user_profile.state:
                        location_data["state"] = user_profile.state

                    diet_preference = user_profile.diet_preference or "not specified"
                    ethnic_group = user_profile.ethnic_group or "not specified"

                    # Build the enhanced profile data with cultural/dietary info
                    profile_data = f"""
                    User Profile Data:
                    - Age: {user_profile.age} years
                    - Height: {user_profile.height} cm
                    - Weight: {user_profile.weight} kg
                    - Sex: {user_profile.sex}
                    - BMI: {user_profile.bmi} ({user_profile.bmi_category})
                    - Body Fat: {user_profile.body_fat}% ({user_profile.body_fat_category})
                    - Daily Calorie Needs: {daily_calories} calories
                    - Country: {location_data.get('country', 'Not specified')}
                    - State/Region: {location_data.get('state', 'Not specified')}
                    - Ethnic Group: {ethnic_group}
                    - Diet Preference: {diet_preference}
                    
                    Based on this profile data, create a weekly meal plan (Monday through Sunday) 
                    with different meals for each day that matches the user's daily calorie needs. The diet plan should be
                    nutritionally balanced and appropriate for their age, sex, body composition, and dietary preferences.
                    
                    IMPORTANT DIETARY INSTRUCTIONS:
                    """

                    # Add detailed dietary instructions based on preferences
                    if diet_preference == 'vegetarian':
                        profile_data += """
                    - The diet plan must be strictly VEGETARIAN with NO meat, fish, or seafood.
                    - Include a variety of plant-based proteins like legumes, tofu, tempeh, and dairy products.
                    """
                    elif diet_preference == 'non-vegetarian':
                        profile_data += """
                    - Include a balanced mix of animal and plant proteins.
                    - You may include meat, fish, and seafood in the meal plan.
                    """
                    else:
                        profile_data += """
                    - Create a balanced diet with a mix of protein sources.
                    - Since no specific diet preference is specified, include a variety of options.
                    """

                    # Add cultural/ethnic-specific instructions
                    profile_data += f"""
                    - Incorporate foods and dishes that are culturally appropriate for someone of {ethnic_group} ethnic background.
                    - Include dishes and ingredients that would be commonly available in {location_data.get('country', 'their country')}
                      and specifically in {location_data.get('state', 'their region')} if possible.
                    - For weekend days (Saturday and Sunday), include more elaborate or special dishes 
                      that people might enjoy during leisure time, while staying within calorie goals.
                    
                    Please format each day exactly like this (with the headers and colons):
                    
                    MONDAY:
                    Breakfast: [detailed breakfast description] (XXX calories)
                    Lunch: [detailed lunch description] (XXX calories)
                    Dinner: [detailed dinner description] (XXX calories)
                    Snacks: [detailed snacks description] (XXX calories)
                    
                    TUESDAY:
                    Breakfast: [detailed breakfast description] (XXX calories)
                    ...
                    
                    [Repeat the same format for each day of the week]
                    
                    Make sure to include the calorie count in parentheses after each meal.
                    The total calories for each day should be approximately {daily_calories} calories.
                    Start your response with "Here's your personalized weekly diet plan based on your calorie needs:"
                    """

                    # Add profile data to the message
                    message = f"{message}\n\n{profile_data}"

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
                max_tokens=3000,
            )

            # Extract the response content
            bot_response = response.choices[0].message.content

            # If this was a diet plan request and the response has the expected format
            if is_diet_plan_request and "here's your personalized" in bot_response.lower():
                try:
                    # Get or create the user's diet plan
                    diet_plan, created = DietPlan.objects.get_or_create(
                        user=request.user)
                    diet_plan.has_diet_plan = True
                    diet_plan.save()

                    # Process each day of the week
                    days = ['monday', 'tuesday', 'wednesday',
                            'thursday', 'friday', 'saturday', 'sunday']
                    days_found = 0  # Count how many days we successfully process

                    for day in days:
                        # Extract day's section from the response using regex
                        day_pattern = rf'{day}:?\s*(.*?)(?=(?:{"|".join(days)}):?|$)'
                        day_match = re.search(
                            day_pattern, bot_response.lower(), re.DOTALL | re.IGNORECASE)

                        if day_match:
                            day_text = day_match.group(1)

                            # Extract meal info for this day
                            breakfast_info = extract_meal_info(
                                day_text, "Breakfast")
                            lunch_info = extract_meal_info(day_text, "Lunch")
                            dinner_info = extract_meal_info(day_text, "Dinner")
                            snacks_info = extract_meal_info(day_text, "Snack")

                            # Only proceed if we have at least some meal info
                            if breakfast_info or lunch_info or dinner_info or snacks_info:
                                # Get or create daily diet plan
                                daily_plan, _ = DailyDietPlan.objects.get_or_create(
                                    diet_plan=diet_plan,
                                    day_of_week=day
                                )

                                # Update with extracted data
                                if breakfast_info:
                                    daily_plan.breakfast = breakfast_info['description']
                                    daily_plan.breakfast_calories = breakfast_info['calories']

                                if lunch_info:
                                    daily_plan.lunch = lunch_info['description']
                                    daily_plan.lunch_calories = lunch_info['calories']

                                if dinner_info:
                                    daily_plan.dinner = dinner_info['description']
                                    daily_plan.dinner_calories = dinner_info['calories']

                                if snacks_info:
                                    daily_plan.snacks = snacks_info['description']
                                    daily_plan.snacks_calories = snacks_info['calories']

                                daily_plan.save()
                                days_found += 1

                    # Add a confirmation to the bot response
                    if days_found > 0:
                        bot_response += f"\n\nI've saved this weekly diet plan to your profile. Successfully processed {days_found} days of the week. You can view and edit it on your dashboard."
                    else:
                        bot_response += "\n\nI couldn't automatically save the diet plan because I couldn't extract the meal information correctly. Please try rephrasing your request."

                    # Add this at the end of the chatbot handler:

                except Exception as e:
                    bot_response += f"\n\nI couldn't automatically save this diet plan due to an error: {str(e)}"

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


def extract_meal_info(text, meal_type):
    """Extract meal description and calories from chatbot response text"""
    import re

    # Handle the difference between "Snack" and "Snacks"
    search_term = meal_type
    if meal_type.lower() == "snack":
        # Search for both "Snack" and "Snacks"
        search_term = r"Snacks??"

    # Look for sections that start with the meal type
    pattern = rf'{search_term}[\s]*:[\s]*(.*?)(?:(?:\(|:)[\s]*(\d+)[\s]*calories[\s]*(?:\)|:)|$)'
    match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)

    if match:
        # The description is in group 1
        description = match.group(1).strip()

        # Calories might be in group 2 if found
        calories_str = match.group(2) if len(match.groups()) > 1 else None

        # Try to convert calories to int
        calories = None
        if calories_str:
            try:
                calories = int(calories_str)
            except ValueError:
                pass

        # If we got a description but no calories, try to find calories separately
        if description and not calories:
            calories_pattern = r'(\d+)\s*(?:kcal|calories)'
            calories_match = re.search(
                calories_pattern, description, re.IGNORECASE)
            if calories_match:
                try:
                    calories = int(calories_match.group(1))
                except ValueError:
                    pass

        # Only return data if we have a description (non-empty)
        if description:
            return {
                'description': description,
                'calories': calories
            }

    return None


@login_required
def save_profile(request):
    if request.method == 'POST':
        # Get data from form
        height = request.POST.get('height')
        weight = request.POST.get('weight')
        sex = request.POST.get('sex')
        age = request.POST.get('age')

        # Get new fields from form
        country = request.POST.get('country')
        state = request.POST.get('state')
        language = request.POST.get('language')
        ethnic_group = request.POST.get('ethnic_group')
        diet_preference = request.POST.get('diet_preference')

        # Handle avatar upload
        avatar = request.FILES.get('avatar')

        # Update user profile
        user_profile = request.user.userprofile
        user_profile.height = height
        user_profile.weight = weight
        user_profile.sex = sex
        user_profile.age = age

        # Update new fields
        user_profile.country = country
        user_profile.state = state
        user_profile.language = language
        user_profile.ethnic_group = ethnic_group
        user_profile.diet_preference = diet_preference

        if avatar:
            user_profile.avatar = avatar

        user_profile.save()

        messages.success(request, "Profile information saved successfully!")
        return redirect('profile')

    return redirect('profile')


@login_required
def update_profile(request):
    if request.method == 'POST':
        # Get data from form
        height = request.POST.get('height')
        weight = request.POST.get('weight')
        sex = request.POST.get('sex')
        age = request.POST.get('age')

        # Get new fields from form
        country = request.POST.get('country')
        state = request.POST.get('state')
        language = request.POST.get('language')
        ethnic_group = request.POST.get('ethnic_group')
        diet_preference = request.POST.get('diet_preference')

        # Handle avatar upload
        avatar = request.FILES.get('avatar')

        # Update user profile
        user_profile = request.user.userprofile
        user_profile.height = height
        user_profile.weight = weight
        user_profile.sex = sex
        user_profile.age = age

        # Update new fields
        user_profile.country = country
        user_profile.state = state
        user_profile.language = language
        user_profile.ethnic_group = ethnic_group
        user_profile.diet_preference = diet_preference

        if avatar:
            user_profile.avatar = avatar

        user_profile.save()

        messages.success(request, "Profile updated successfully!")
        return redirect('profile')

    # Display the form with current values
    user_profile = request.user.userprofile
    context = {
        'height': user_profile.height,
        'weight': user_profile.weight,
        'sex': user_profile.sex,
        'age': user_profile.age,
        'country': user_profile.country,
        'state': user_profile.state,
        'language': user_profile.language,
        'ethnic_group': user_profile.ethnic_group,
        'diet_preference': user_profile.diet_preference,
    }
    return render(request, 'fitness/update_profile.html', context)


@login_required
def save_notification_preference(request):
    if request.method == 'POST':
        preference = request.POST.get('notification_preference')
        if preference in ['daily', 'weekly', 'none']:
            user_profile = request.user.userprofile
            user_profile.notification_preference = preference
            user_profile.save()
            messages.success(
                request, "Notification preferences updated successfully!")
        else:
            messages.error(request, "Invalid notification preference.")
        return redirect('profile')
    return redirect('profile')


@login_required
def edit_diet(request):
    # Get the day parameter from the URL
    day = request.GET.get('day', 'monday').lower()

    # Get or create the user's diet plan
    diet_plan, created = DietPlan.objects.get_or_create(user=request.user)

    if created:
        diet_plan.has_diet_plan = True
        diet_plan.save()

    # Get or create the daily plan
    daily_plan, created = DailyDietPlan.objects.get_or_create(
        diet_plan=diet_plan,
        day_of_week=day
    )

    # Get the display name for the day
    day_display = dict(DailyDietPlan.DAYS_OF_WEEK).get(day, day.capitalize())

    # Get user profile for notifications
    user_profile = request.user.userprofile

    # Check if user should see notifications
    show_notification = False
    notification_message = ""

    if user_profile.notification_preference != 'none':
        import datetime
        today = datetime.datetime.now()

        if user_profile.notification_preference == 'daily':
            show_notification = True
            notification_message = f"Remember to follow your {today.strftime('%A')} diet plan!"
        elif user_profile.notification_preference == 'weekly' and today.weekday() == 0:  # Monday
            show_notification = True
            notification_message = "Here's your weekly diet plan reminder!"

    context = {
        'day': day,
        'day_display': day_display,
        'daily_plan': daily_plan,
        'has_notifications': show_notification,
        'notification_message': notification_message,
    }

    # Add notification when diet plan is edited
    add_notification(
        request, f"You've updated your diet plan for {day_display}.", "success")

    return render(request, 'fitness/edit_diet.html', context)


@login_required
def save_diet(request):
    if request.method == 'POST':
        day = request.POST.get('day')

        # Get the diet plan
        diet_plan, created = DietPlan.objects.get_or_create(user=request.user)
        if created or not diet_plan.has_diet_plan:
            diet_plan.has_diet_plan = True
            diet_plan.save()

        # Get or create the daily plan
        daily_plan, created = DailyDietPlan.objects.get_or_create(
            diet_plan=diet_plan,
            day_of_week=day
        )

        # Update the daily plan with form data
        daily_plan.breakfast = request.POST.get('breakfast')
        daily_plan.lunch = request.POST.get('lunch')
        daily_plan.dinner = request.POST.get('dinner')
        daily_plan.snacks = request.POST.get('snacks')

        # Update calories if provided
        breakfast_calories = request.POST.get('breakfast_calories')
        if breakfast_calories:
            try:
                daily_plan.breakfast_calories = int(breakfast_calories)
            except ValueError:
                daily_plan.breakfast_calories = None
        else:
            daily_plan.breakfast_calories = None

        lunch_calories = request.POST.get('lunch_calories')
        if lunch_calories:
            try:
                daily_plan.lunch_calories = int(lunch_calories)
            except ValueError:
                daily_plan.lunch_calories = None
        else:
            daily_plan.lunch_calories = None

        dinner_calories = request.POST.get('dinner_calories')
        if dinner_calories:
            try:
                daily_plan.dinner_calories = int(dinner_calories)
            except ValueError:
                daily_plan.dinner_calories = None
        else:
            daily_plan.dinner_calories = None

        snacks_calories = request.POST.get('snacks_calories')
        if snacks_calories:
            try:
                daily_plan.snacks_calories = int(snacks_calories)
            except ValueError:
                daily_plan.snacks_calories = None
        else:
            daily_plan.snacks_calories = None

        daily_plan.save()

        # Show success message
        messages.success(
            request, f"Your diet plan for {day.capitalize()} has been updated!")

        # Fix the redirect URL - use 'index' named URL with query parameter
        return redirect(f'/?day={day}')  # Changed from '/index/?day={day}'

    # If not POST, redirect to dashboard
    return redirect('index')


@login_required
def diet_tracker(request):
    # Check if user profile is complete
    user_profile = request.user.userprofile
    profile_complete = bool(
        user_profile.height and
        user_profile.weight and
        user_profile.sex and
        user_profile.age
    )

    # If profile is incomplete, redirect to profile page with a message
    if not profile_complete:
        messages.warning(
            request,
            "Please complete your profile before using the diet tracker. We need your height, weight, sex, and age to provide accurate diet analysis and recommendations."
        )
        return redirect('profile')

    # Get the current day
    import datetime
    current_day = datetime.datetime.now().strftime('%A').lower()

    # Get user's diet plan
    try:
        diet_plan = DietPlan.objects.get(user=request.user)
        daily_plan = diet_plan.get_day_plan(current_day)
    except DietPlan.DoesNotExist:
        diet_plan = None
        daily_plan = None

    # Get user profile for stats
    user_profile = request.user.userprofile

    context = {
        'current_day': current_day.title(),
        'daily_plan': daily_plan,
    }

    if request.method == 'POST':
        food_description = request.POST.get('food_description', '')
        # breakfast, lunch, dinner, or snack
        food_type = request.POST.get('food_type', '')
        food_image = request.FILES.get('food_image', None)

        # Initialize response message
        response_message = None
        analyzed_food = None
        calories = None

        # Initialize the OpenAI client
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Prepare the system message for food analysis
        system_message = """You are a nutrition expert. Analyze the food description or image provided.
        Provide a detailed description of the food and estimate its calorie content.
        Your response should be in JSON format with two fields:
        1. description: A detailed description of the food
        2. calories: An integer estimate of the calories
        Example: {"description": "Grilled chicken breast with steamed broccoli and brown rice", "calories": 450}"""

        messages = [{"role": "system", "content": system_message}]

        # Process either image or text
        if food_image:
            # Convert image to base64
            import base64
            image_data = food_image.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Create content list with text and image
            content = [
                {"type": "text", "text": f"Analyze this food image. What food is this and how many calories does it contain?"}
            ]

            # Add the image content
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{food_image.content_type};base64,{base64_image}"
                }
            })

            # Add to messages
            messages.append({"role": "user", "content": content})
        elif food_description:
            # Text-only message
            messages.append(
                {"role": "user", "content": f"Food to analyze: {food_description}"})
        else:
            messages.error(
                request, "Please provide either a food description or an image.")
            return render(request, 'fitness/diet_tracker.html', context)

        try:
            # Generate response using GPT-4o
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                temperature=0.7,
                max_tokens=1000,
            )

            # Extract the response content
            ai_response = response.choices[0].message.content

            # Try to parse JSON from the response
            import json
            import re

            # Look for JSON in the response
            json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
            if json_match:
                try:
                    food_data = json.loads(json_match.group(0))
                    analyzed_food = food_data.get('description', '')
                    calories = food_data.get('calories', 0)
                except json.JSONDecodeError:
                    # If JSON parsing fails, try to extract information from text
                    analyzed_food = ai_response
                    calories_match = re.search(
                        r'(\d+)\s*calories', ai_response, re.IGNORECASE)
                    if calories_match:
                        calories = int(calories_match.group(1))
            else:
                # If no JSON found, use the whole response as description
                analyzed_food = ai_response
                calories_match = re.search(
                    r'(\d+)\s*calories', ai_response, re.IGNORECASE)
                if calories_match:
                    calories = int(calories_match.group(1))

            # If only food name is provided (without image), extract just the food name
            if food_description and not food_image:
                # Extract just the name of the food (first few words)
                food_name = food_description.split(',')[0].strip()
                if len(food_name.split()) > 5:  # Limit to 5 words max
                    food_name = ' '.join(food_name.split()[:5])

                # Store the actual analysis in a variable for display
                full_analyzed_food = analyzed_food

                # Use simple food name for updating the plan
                analyzed_food = food_name

            # Update the user's diet plan based on the food type
            if food_type in ['breakfast', 'lunch', 'dinner', 'snacks']:
                # Get or create diet plan and daily plan
                if not diet_plan:
                    diet_plan = DietPlan.objects.create(
                        user=request.user, has_diet_plan=True)

                if not daily_plan:
                    daily_plan = DailyDietPlan.objects.create(
                        diet_plan=diet_plan,
                        day_of_week=current_day
                    )

                # Update the specified meal with just the food name
                setattr(daily_plan, food_type, analyzed_food)
                setattr(daily_plan, f"{food_type}_calories", calories)
                daily_plan.save()

                response_message = f"Your {food_type} has been updated!"

                # Compare with planned diet and update future days if needed
                update_future_diet_plans(request.user, daily_plan, current_day)

            # For displaying in the results, use the full analysis if available
            if 'full_analyzed_food' in locals():
                context['full_analyzed_food'] = full_analyzed_food

            context['response_message'] = response_message
            context['analyzed_food'] = analyzed_food
            context['calories'] = calories
            context['food_type'] = food_type
            # Update context with the updated daily plan
            context['daily_plan'] = daily_plan

            # Add notification about the tracked meal
            add_notification(
                request, f"You've tracked your {food_type} for today.", "success")

        except Exception as e:
            messages.error(request, f"Error analyzing food: {str(e)}")

    return render(request, 'fitness/diet_tracker.html', context)


def update_future_diet_plans(user, current_daily_plan, current_day):
    """
    Compare the tracked diet with the planned diet and update future days if needed
    """
    try:
        # Get all days of the week in order starting from tomorrow
        import datetime
        days = ['monday', 'tuesday', 'wednesday',
                'thursday', 'friday', 'saturday', 'sunday']
        current_day_index = days.index(current_day)
        future_days = days[current_day_index+1:] + days[:current_day_index]

        # Get the user's diet plan
        diet_plan = DietPlan.objects.get(user=user)

        # Get user profile for AI to use in generating new plans
        user_profile = user.userprofile
        profile_data = ""
        daily_calories = None

        if user_profile.height and user_profile.weight and user_profile.sex and user_profile.age:
            daily_calories = user_profile.daily_calorie_needs
            profile_data = f"""
            User Profile Data:
            - Age: {user_profile.age} years
            - Height: {user_profile.height} cm
            - Weight: {user_profile.weight} kg
            - Sex: {user_profile.sex}
            - BMI: {user_profile.bmi} ({user_profile.bmi_category})
            - Body Fat: {user_profile.body_fat}% ({user_profile.body_fat_category})
            - Daily Calorie Needs: {daily_calories} calories
            """

        # Get current tracked diet
        current_diet = f"""
        Current Tracked Diet ({current_day.capitalize()}):
        - Breakfast: {current_daily_plan.breakfast or 'None'} ({current_daily_plan.breakfast_calories or 0} calories)
        - Lunch: {current_daily_plan.lunch or 'None'} ({current_daily_plan.lunch_calories or 0} calories)
        - Dinner: {current_daily_plan.dinner or 'None'} ({current_daily_plan.dinner_calories or 0} calories)
        - Snacks: {current_daily_plan.snacks or 'None'} ({current_daily_plan.snacks_calories or 0} calories)
        """

        # Initialize the OpenAI client
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Update each future day
        for day in future_days:
            # Get or create the daily plan for this day
            future_plan, created = DailyDietPlan.objects.get_or_create(
                diet_plan=diet_plan,
                day_of_week=day
            )

            # Check if it's a weekend day (Saturday or Sunday)
            if day in ['saturday', 'sunday']:
                # Use the specialized weekend diet plan function
                create_weekend_diet_plan(
                    user, day, future_plan, current_daily_plan, current_day)
                continue

            # Prepare message for OpenAI
            calorie_instruction = ""
            if daily_calories:
                calorie_instruction = f"The total calories for the day should be approximately {daily_calories} calories."

            prompt = f"""
            Based on the user's profile and their tracked diet for {current_day.capitalize()}, 
            please generate an appropriate complete diet plan for {day.capitalize()}.
            
            {profile_data}
            
            {current_diet}
            
            Create a comprehensive meal plan for {day.capitalize()} that is balanced and appropriate for the user's profile.
            {calorie_instruction}
            
            The output should be in JSON format with these fields:
            {{
                "breakfast": "detailed breakfast description",
                "breakfast_calories": calories_as_integer,
                "lunch": "detailed lunch description",
                "lunch_calories": calories_as_integer,
                "dinner": "detailed dinner description",
                "dinner_calories": calories_as_integer,
                "snacks": "detailed snacks description",
                "snacks_calories": calories_as_integer
            }}
            
            Make sure the meal plan is nutritionally balanced and appropriate for the user's profile.
            """

            try:
                # Generate new meal plan
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=3000,
                )

                # Extract JSON from response
                ai_response = response.choices[0].message.content

                # Try to parse JSON from the response
                import json
                import re

                # Look for JSON in the response
                json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
                if json_match:
                    try:
                        meal_plan = json.loads(json_match.group(0))

                        # Update the future day's plan
                        future_plan.breakfast = meal_plan.get(
                            'breakfast', future_plan.breakfast)
                        future_plan.breakfast_calories = meal_plan.get(
                            'breakfast_calories', future_plan.breakfast_calories)
                        future_plan.lunch = meal_plan.get(
                            'lunch', future_plan.lunch)
                        future_plan.lunch_calories = meal_plan.get(
                            'lunch_calories', future_plan.lunch_calories)
                        future_plan.dinner = meal_plan.get(
                            'dinner', future_plan.dinner)
                        future_plan.dinner_calories = meal_plan.get(
                            'dinner_calories', future_plan.dinner_calories)
                        future_plan.snacks = meal_plan.get(
                            'snacks', future_plan.snacks)
                        future_plan.snacks_calories = meal_plan.get(
                            'snacks_calories', future_plan.snacks_calories)
                        future_plan.save()
                    except json.JSONDecodeError:
                        # If JSON parsing fails, skip this day
                        continue

            except Exception as e:
                # If there's an error, continue to the next day
                print(f"Error updating {day} diet plan: {str(e)}")
                continue

    except Exception as e:
        # Log any errors but don't interrupt the user experience
        print(f"Error in update_future_diet_plans: {str(e)}")


def create_weekend_diet_plan(user, day, daily_plan, current_daily_plan, current_day):
    """
    Creates a specialized weekend diet plan based on user's location, ethnic group, and dietary preferences
    """
    try:
        # Get user profile data
        user_profile = user.userprofile

        # Check if profile has required data
        if not all([user_profile.height, user_profile.weight, user_profile.sex, user_profile.age]):
            # Can't create personalized plan without basic info
            return

        # Get specific profile data for cultural/dietary requirements
        daily_calories = user_profile.daily_calorie_needs
        location_data = {}

        # Add location data if available
        if user_profile.country:
            location_data["country"] = user_profile.country
        if user_profile.state:
            location_data["state"] = user_profile.state

        # Get dietary preference
        diet_preference = user_profile.diet_preference or "not specified"

        # Get ethnic group
        ethnic_group = user_profile.ethnic_group or "not specified"

        # Build the complete profile data
        profile_data = f"""
        User Profile Data:
        - Age: {user_profile.age} years
        - Height: {user_profile.height} cm
        - Weight: {user_profile.weight} kg
        - Sex: {user_profile.sex}
        - BMI: {user_profile.bmi} ({user_profile.bmi_category})
        - Body Fat: {user_profile.body_fat}% ({user_profile.body_fat_category})
        - Daily Calorie Needs: {daily_calories} calories
        - Country: {location_data.get('country', 'Not specified')}
        - State/Region: {location_data.get('state', 'Not specified')}
        - Ethnic Group: {ethnic_group}
        - Diet Preference: {diet_preference}
        """

        # Get current tracked diet
        current_diet = f"""
        Current Tracked Diet ({current_day.capitalize()}):
        - Breakfast: {current_daily_plan.breakfast or 'None'} ({current_daily_plan.breakfast_calories or 0} calories)
        - Lunch: {current_daily_plan.lunch or 'None'} ({current_daily_plan.lunch_calories or 0} calories)
        - Dinner: {current_daily_plan.dinner or 'None'} ({current_daily_plan.dinner_calories or 0} calories)
        - Snacks: {current_daily_plan.snacks or 'None'} ({current_daily_plan.snacks_calories or 0} calories)
        """

        # Prepare message for OpenAI
        calorie_instruction = ""
        if daily_calories:
            calorie_instruction = f"The total calories for the day should be approximately {daily_calories} calories."

        # Create tailored prompt based on user's cultural and dietary preferences
        dietary_instructions = """
        IMPORTANT DIETARY INSTRUCTIONS:
        """

        # Add instructions based on dietary preference
        if diet_preference == 'vegetarian':
            dietary_instructions += """
        - The diet plan must be strictly VEGETARIAN with NO meat, fish, or seafood.
        - Include a variety of plant-based proteins like legumes, tofu, tempeh, and dairy products.
        """
        elif diet_preference == 'non-vegetarian':
            dietary_instructions += """
        - Include a balanced mix of animal and plant proteins.
        - You may include meat, fish, and seafood in the meal plan.
        """
        else:
            dietary_instructions += """
        - Create a balanced diet with a mix of protein sources.
        - Since no specific diet preference is specified, include a variety of options.
        """

        # Add cultural/ethnic-specific instructions
        dietary_instructions += f"""
        - Incorporate foods and dishes that are culturally appropriate for someone of {ethnic_group} ethnic background.
        - Include dishes and ingredients that would be commonly available in {location_data.get('country', 'their country')}
          and specifically in {location_data.get('state', 'their region')} if possible.
        - For weekend meals, include more elaborate or special dishes that people might enjoy during leisure time.
        - {day.capitalize()} meals should feel special compared to weekday meals, while staying within calorie goals.
        """

        prompt = f"""
        Create a specialized {day.capitalize()} diet plan tailored to the user's profile, location, and cultural background.
        
        {profile_data}
        
        {current_diet}
        
        {dietary_instructions}
        
        Create a comprehensive and culturally appropriate meal plan for {day.capitalize()} that aligns with the user's:
        1. Calorie needs ({calorie_instruction})
        2. Dietary preference (vegetarian/non-vegetarian as specified)
        3. Cultural and ethnic background
        4. Geographic location (using locally available ingredients)
        
        Since this is a weekend day, make the meals slightly more special, flavorful and elaborate than weekday meals,
        while ensuring they remain healthy and within calorie goals.
        
        The output MUST be in this exact JSON format with no extra text:
        {{
            "breakfast": "detailed breakfast description",
            "breakfast_calories": calories_as_integer,
            "lunch": "detailed lunch description",
            "lunch_calories": calories_as_integer,
            "dinner": "detailed dinner description",
            "dinner_calories": calories_as_integer,
            "snacks": "detailed snacks description",
            "snacks_calories": calories_as_integer
        }}
        """

        # Initialize the OpenAI client
        client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Generate new weekend meal plan
        response = client.chat.completions.create(
            model="gpt-4o",  # Using GPT-4o as specified
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=3000,
        )

        # Extract JSON from response
        ai_response = response.choices[0].message.content

        # Parse JSON from the response
        import json
        import re

        # Look for JSON in the response
        json_match = re.search(r'\{.*\}', ai_response, re.DOTALL)
        if json_match:
            try:
                meal_plan = json.loads(json_match.group(0))

                # Update the weekend day's plan
                daily_plan.breakfast = meal_plan.get(
                    'breakfast', daily_plan.breakfast)
                daily_plan.breakfast_calories = meal_plan.get(
                    'breakfast_calories', daily_plan.breakfast_calories)
                daily_plan.lunch = meal_plan.get('lunch', daily_plan.lunch)
                daily_plan.lunch_calories = meal_plan.get(
                    'lunch_calories', daily_plan.lunch_calories)
                daily_plan.dinner = meal_plan.get('dinner', daily_plan.dinner)
                daily_plan.dinner_calories = meal_plan.get(
                    'dinner_calories', daily_plan.dinner_calories)
                daily_plan.snacks = meal_plan.get('snacks', daily_plan.snacks)
                daily_plan.snacks_calories = meal_plan.get(
                    'snacks_calories', daily_plan.snacks_calories)
                daily_plan.save()
                return True
            except json.JSONDecodeError:
                print(f"JSON decode error in weekend diet plan for {day}")
                return False
        else:
            print(f"No JSON found in response for {day} diet plan")
            return False

    except Exception as e:
        # Log any errors but don't interrupt the user experience
        print(f"Error in create_weekend_diet_plan for {day}: {str(e)}")
        return False


@login_required
def update_diet(request):
    """View to update diet plan for a specified day"""
    # Get the day parameter from the URL
    day = request.GET.get('day', 'monday').lower()

    # Get or create the user's diet plan
    diet_plan, created = DietPlan.objects.get_or_create(user=request.user)

    if created:
        diet_plan.has_diet_plan = True
        diet_plan.save()

    # Get or create the daily plan
    daily_plan, created = DailyDietPlan.objects.get_or_create(
        diet_plan=diet_plan,
        day_of_week=day
    )

    # Redirect to edit_diet view with the day parameter
    return redirect(f'/edit-diet/?day={day}')


@login_required
def exercise_tracker(request):
    # Check if user profile is complete
    user_profile = request.user.userprofile
    profile_complete = bool(
        user_profile.height and
        user_profile.weight and
        user_profile.sex and
        user_profile.age
    )

    # If profile is incomplete, redirect to profile page with a message
    if not profile_complete:
        messages.warning(
            request,
            "Please complete your profile before using the exercise tracker. We need your height, weight, sex, and age to provide personalized exercise recommendations."
        )
        return redirect('profile')

    # Check if user already has a saved exercise plan
    try:
        exercise_plan_obj = ExercisePlan.objects.get(user=request.user)
        # User already has a plan, check if they want to create a new one
        if request.GET.get('new_plan') == 'true' or request.method == 'POST':
            # Will generate a new plan below
            pass
        else:
            # Prepare existing plan for template
            exercise_plan = {
                'schedule': [],
                'tips': [tip.text for tip in exercise_plan_obj.tips.all()],
                'precautions': [precaution.text for precaution in exercise_plan_obj.precautions.all()]
            }

            # Add days to the schedule
            for day in exercise_plan_obj.days.all().order_by('id'):
                day_dict = {
                    'day': day.day,
                    'focus': day.focus,
                    'warmup': day.warmup,
                    'cooldown': day.cooldown,
                    'duration': day.duration,
                    'exercises': []
                }

                # Add exercises to each day
                for exercise in day.exercises.all():
                    day_dict['exercises'].append({
                        'name': exercise.name,
                        'sets': exercise.sets,
                        'reps': exercise.reps,
                        'rest': exercise.rest,
                        'notes': exercise.notes
                    })

                exercise_plan['schedule'].append(day_dict)

            return render(request, 'fitness/exercise_tracker.html', {
                'exercise_plan': exercise_plan,
                'fitness_level': exercise_plan_obj.fitness_level,
                'created_at': exercise_plan_obj.created_at,
                'last_updated': exercise_plan_obj.last_updated,
            })
    except ExercisePlan.DoesNotExist:
        # No existing plan, will generate a new one if POST
        pass

    if request.method == 'POST':
        fitness_level = request.POST.get('fitness_level')
        if fitness_level in ['beginner', 'intermediate', 'advanced']:
            # Get user profile data for personalized recommendations
            height = user_profile.height
            weight = user_profile.weight
            sex = user_profile.sex
            age = user_profile.age
            bmi = user_profile.bmi
            bmi_category = user_profile.bmi_category
            body_fat = user_profile.body_fat
            body_fat_category = user_profile.body_fat_category

            # Get API key from environment
            api_key = os.environ.get("OPENAI_API_KEY")

            # Initialize the OpenAI client
            client = openai.OpenAI(api_key=api_key)

            # Create a simpler prompt to avoid JSON parsing issues
            prompt = f"""
                Generate a personalized gym exercise plan for a {fitness_level} level user with the following profile:
                - Height: {height} cm
                - Weight: {weight} kg
                - Sex: {sex}
                - Age: {age} years
                - BMI: {bmi} ({bmi_category})
                - Body Fat: {body_fat}% ({body_fat_category})

            This plan should be tailored to their fitness level ({fitness_level}) and account for their body metrics.
            
            Include a 7-day weekly schedule (Monday-Sunday) with specific exercises, sets, reps, rest periods, 
            warm-ups, cool-downs, and duration for each day.
            
            Format your response as clean, valid JSON with this structure:
                {{
                    "schedule": [
                        {{
                            "day": "Monday",
                        "focus": "Chest and Triceps",
                            "exercises": [
                                {{
                                "name": "Bench Press",
                                    "sets": 3,
                                "reps": "8-10",
                                "rest": "90 seconds",
                                "notes": "Keep shoulders back"
                            }}
                        ],
                        "warmup": "5 minutes cardio plus dynamic stretching",
                        "cooldown": "Static stretching for chest and arms",
                        "duration": "45 minutes"
                    }}
                ],
                "tips": ["Tip 1", "Tip 2", "Tip 3"],
                "precautions": ["Precaution 1", "Precaution 2"]
            }}

            Return ONLY the JSON with NO additional text or formatting.
            """

            try:
                # Generate exercise plan with structured prompt
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a fitness expert that outputs only clean, valid JSON."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.7,
                    max_tokens=4000,
                    # Explicitly request JSON format
                    response_format={"type": "json_object"}
                )

                # Get the response content
                ai_response = response.choices[0].message.content

                # Try to parse JSON
                import json

                try:
                    # Direct parsing
                    exercise_plan = json.loads(ai_response)

                    # Delete any existing plan
                    ExercisePlan.objects.filter(user=request.user).delete()

                    # Create a new plan in the database
                    exercise_plan_obj = ExercisePlan.objects.create(
                        user=request.user,
                        fitness_level=fitness_level
                    )

                    # Add days
                    for day_data in exercise_plan['schedule']:
                        day = ExerciseDay.objects.create(
                            exercise_plan=exercise_plan_obj,
                            day=day_data['day'],
                            focus=day_data['focus'],
                            warmup=day_data['warmup'],
                            cooldown=day_data['cooldown'],
                            duration=day_data['duration']
                        )

                        # Add exercises for each day
                        for exercise_data in day_data['exercises']:
                            Exercise.objects.create(
                                exercise_day=day,
                                name=exercise_data['name'],
                                sets=exercise_data['sets'],
                                reps=exercise_data['reps'],
                                rest=exercise_data['rest'],
                                notes=exercise_data.get('notes', '')
                            )

                    # Add tips
                    for tip in exercise_plan['tips']:
                        ExerciseTip.objects.create(
                            exercise_plan=exercise_plan_obj,
                            text=tip
                        )

                    # Add precautions
                    for precaution in exercise_plan['precautions']:
                        ExercisePrecaution.objects.create(
                            exercise_plan=exercise_plan_obj,
                            text=precaution
                        )

                    # Add a notification to the session
                    add_notification(
                        request,
                        f"Your personalized {fitness_level} exercise plan has been created!",
                        "success"
                    )

                    messages.success(
                        request, "Your personalized exercise plan has been created!")

                    # Redirect to plan display page
                    return redirect('view_exercise_plan')

                except json.JSONDecodeError as e:
                    messages.error(
                        request, "Error creating exercise plan. Please try again.")
                    return redirect('exercise_tracker')

            except Exception as e:
                messages.error(
                    request, "Error connecting to our fitness expert. Please try again later.")
                return redirect('exercise_tracker')

    # Display the form if no POST or GET or no existing plan
    return render(request, 'fitness/exercise_tracker.html', {
        'exercise_plan': None,
        'fitness_level': None
    })


@login_required
def view_exercise_plan(request):
    """View to display the saved exercise plan"""
    try:
        # Get the user's exercise plan
        exercise_plan_obj = ExercisePlan.objects.get(user=request.user)

        # Prepare plan for template
        exercise_plan = {
            'schedule': [],
            'tips': [tip.text for tip in exercise_plan_obj.tips.all()],
            'precautions': [precaution.text for precaution in exercise_plan_obj.precautions.all()]
        }

        # Add days to the schedule
        for day in exercise_plan_obj.days.all().order_by('id'):
            day_dict = {
                'day': day.day,
                'focus': day.focus,
                'warmup': day.warmup,
                'cooldown': day.cooldown,
                'duration': day.duration,
                'exercises': []
            }

            # Add exercises to each day
            for exercise in day.exercises.all():
                day_dict['exercises'].append({
                    'name': exercise.name,
                    'sets': exercise.sets,
                    'reps': exercise.reps,
                    'rest': exercise.rest,
                    'notes': exercise.notes
                })

            exercise_plan['schedule'].append(day_dict)

        return render(request, 'fitness/view_exercise_plan.html', {
            'exercise_plan': exercise_plan,
            'fitness_level': exercise_plan_obj.fitness_level,
            'created_at': exercise_plan_obj.created_at,
            'last_updated': exercise_plan_obj.last_updated,
        })

    except ExercisePlan.DoesNotExist:
        messages.warning(
            request, "You don't have an exercise plan yet. Let's create one!")
        return redirect('exercise_tracker')


@login_required
def health_tracker(request):
    # Check if user profile is complete
    user_profile = request.user.userprofile
    profile_complete = bool(
        user_profile.height and
        user_profile.weight and
        user_profile.sex and
        user_profile.age
    )

    # If profile is incomplete, redirect to profile page with a message
    if not profile_complete:
        messages.warning(
            request,
            "Please complete your profile before using the health tracker. We need your height, weight, sex, and age to provide accurate health analysis."
        )
        return redirect('profile')

    # Get previous health data for comparison
    try:
        previous_health_data = HealthData.objects.filter(
            user=request.user).order_by('-date')[:5]
        has_previous_data = previous_health_data.exists()
    except:
        previous_health_data = []
        has_previous_data = False

    if request.method == 'POST':
        # Initialize variables
        health_data = {}
        health_image = request.FILES.get('health_image', None)

        # Get manually entered data if provided
        heart_rate = request.POST.get('heart_rate', None)
        steps = request.POST.get('steps', None)
        calories_burnt = request.POST.get('calories_burnt', None)
        sleep_hours = request.POST.get('sleep_hours', None)
        blood_pressure = request.POST.get('blood_pressure', None)
        oxygen_level = request.POST.get('oxygen_level', None)

        # Check if we have either manual data or an image
        if health_image:
            # Process image with AI
            import base64

            # Read the image data
            image_data = health_image.read()
            # Convert to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')

            # Initialize the OpenAI client
            client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

            # Prepare the system message
            system_message = """You are a health data analyzer. Extract health metrics from fitness tracker images.
            Analyze the image for these metrics and return them in JSON format:
            {
                "heart_rate": numeric value or null,
                "steps": numeric value or null,
                "calories_burnt": numeric value or null,
                "sleep_hours": numeric value or null,
                "blood_pressure": string or null,
                "oxygen_level": numeric value or null,
                "additional_metrics": {any other metrics found}
            }
            If you can't identify a specific metric, set its value to null."""

            # Prepare messages for the API call
            content = [
                {"type": "text", "text": "Analyze this fitness tracker image and extract health metrics."}
            ]

            # Add the image content
            content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/{health_image.content_type};base64,{base64_image}"
                }
            })

            # Make the API call
            try:
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": content}
                    ],
                    temperature=0.7,
                    max_tokens=1000,
                    response_format={"type": "json_object"}
                )

                # Parse the response
                import json
                health_data = json.loads(response.choices[0].message.content)

                # Override with manual entries if provided
                if heart_rate:
                    health_data['heart_rate'] = int(heart_rate)
                if steps:
                    health_data['steps'] = int(steps)
                if calories_burnt:
                    health_data['calories_burnt'] = int(calories_burnt)
                if sleep_hours:
                    health_data['sleep_hours'] = float(sleep_hours)
                if blood_pressure:
                    health_data['blood_pressure'] = blood_pressure
                if oxygen_level:
                    health_data['oxygen_level'] = int(oxygen_level)

            except Exception as e:
                messages.error(
                    request, f"Error analyzing health data image: {str(e)}")
                health_data = {}

        elif any([heart_rate, steps, calories_burnt, sleep_hours, blood_pressure, oxygen_level]):
            # Process manually entered data
            health_data = {
                "heart_rate": int(heart_rate) if heart_rate else None,
                "steps": int(steps) if steps else None,
                "calories_burnt": int(calories_burnt) if calories_burnt else None,
                "sleep_hours": float(sleep_hours) if sleep_hours else None,
                "blood_pressure": blood_pressure if blood_pressure else None,
                "oxygen_level": int(oxygen_level) if oxygen_level else None,
                "additional_metrics": {}
            }
        else:
            messages.error(
                request, "Please provide either health metrics or upload an image.")
            return render(request, 'fitness/health_tracker.html', {
                'previous_data': previous_health_data,
                'has_previous_data': has_previous_data
            })

        # Save the data to the database
        try:
            # Create new health data entry
            new_health_data = HealthData.objects.create(
                user=request.user,
                heart_rate=health_data.get('heart_rate'),
                steps=health_data.get('steps'),
                calories_burnt=health_data.get('calories_burnt'),
                sleep_hours=health_data.get('sleep_hours'),
                blood_pressure=health_data.get('blood_pressure'),
                oxygen_level=health_data.get('oxygen_level'),
                additional_data=health_data.get('additional_metrics', {})
            )

            # Calculate improvements if previous data exists
            improvements = {}
            last_record = None

            if has_previous_data:
                last_record = previous_health_data[0]

                # Calculate heart rate improvement
                if new_health_data.heart_rate and last_record.heart_rate:
                    # For heart rate, lower can be better if previously elevated
                    if 60 <= new_health_data.heart_rate <= 100:
                        if new_health_data.heart_rate < last_record.heart_rate and last_record.heart_rate > 100:
                            improvements['heart_rate'] = f"Improved by {last_record.heart_rate - new_health_data.heart_rate} bpm"
                        elif new_health_data.heart_rate > last_record.heart_rate and last_record.heart_rate < 60:
                            improvements['heart_rate'] = f"Improved by {new_health_data.heart_rate - last_record.heart_rate} bpm"

                # Steps improvement
                if new_health_data.steps and last_record.steps:
                    step_diff = new_health_data.steps - last_record.steps
                    if step_diff > 0:
                        improvements['steps'] = f"Increased by {step_diff} steps"

                # Calories burnt improvement
                if new_health_data.calories_burnt and last_record.calories_burnt:
                    cal_diff = new_health_data.calories_burnt - last_record.calories_burnt
                    if cal_diff > 0:
                        improvements['calories_burnt'] = f"Increased by {cal_diff} calories"

                # Sleep hours improvement
                if new_health_data.sleep_hours and last_record.sleep_hours:
                    if 7 <= new_health_data.sleep_hours <= 9:
                        if new_health_data.sleep_hours > last_record.sleep_hours and last_record.sleep_hours < 7:
                            improvements['sleep_hours'] = f"Improved by {new_health_data.sleep_hours - last_record.sleep_hours:.1f} hours"

                # Oxygen level improvement
                if new_health_data.oxygen_level and last_record.oxygen_level:
                    o2_diff = new_health_data.oxygen_level - last_record.oxygen_level
                    if o2_diff > 0 and last_record.oxygen_level < 95:
                        improvements['oxygen_level'] = f"Improved by {o2_diff}%"

            # Add notification
            improvements_text = ", ".join(
                [f"{k.replace('_', ' ').title()}: {v}" for k, v in improvements.items()])
            notification_text = "Health data updated successfully"

            if improvements_text:
                notification_text += f". Improvements: {improvements_text}"

            add_notification(request, notification_text, "success")

            messages.success(request, "Health data updated successfully!")

            # Refresh the list of previous health data
            previous_health_data = HealthData.objects.filter(
                user=request.user).order_by('-date')[:5]
            has_previous_data = True

            return render(request, 'fitness/health_tracker.html', {
                'current_data': new_health_data,
                'previous_data': previous_health_data,
                'has_previous_data': has_previous_data,
                'improvements': improvements,
                'last_record': last_record
            })

        except Exception as e:
            messages.error(request, f"Error saving health data: {str(e)}")

    # For GET requests or if POST fails
    return render(request, 'fitness/health_tracker.html', {
        'previous_data': previous_health_data,
        'has_previous_data': has_previous_data
    })


@login_required
def community(request):
    """View for the community page"""
    user = request.user
    context = {}

    # If the user is a superuser, get all users for the left panel
    if user.is_superuser:
        all_users = User.objects.exclude(id=user.id).order_by('username')
        context['all_users'] = all_users

        # If a specific user is selected, get chat with that user
        selected_user_id = request.GET.get('user_id')
        if selected_user_id:
            try:
                selected_user = User.objects.get(id=selected_user_id)
                context['selected_user'] = selected_user

                # Get messages between superuser and selected user (both directions)
                chat_messages = CommunityMessage.objects.filter(
                    (Q(sender=user) & Q(receiver=selected_user)) |
                    (Q(sender=selected_user) & Q(receiver=user))
                ).order_by('timestamp')

                # Mark messages as read
                unread_messages = chat_messages.filter(
                    receiver=user, is_read=False)
                unread_messages.update(is_read=True)

                context['chat_messages'] = chat_messages

                # If this is an AJAX request, return only the messages part
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return render(request, 'fitness/partials/chat_messages.html', context)

            except User.DoesNotExist:
                pass
    else:
        # For normal users, show chat with admin (superuser)
        admin_users = User.objects.filter(is_superuser=True)

        if admin_users.exists():
            admin_user = admin_users.first()
            context['admin_user'] = admin_user

            # Get messages between user and admin (both directions)
            chat_messages = CommunityMessage.objects.filter(
                (Q(sender=user) & Q(receiver=admin_user)) |
                (Q(sender=admin_user) & Q(receiver=user))
            ).order_by('timestamp')

            # Mark messages as read
            unread_messages = chat_messages.filter(
                receiver=user, is_read=False)
            unread_messages.update(is_read=True)

            context['chat_messages'] = chat_messages

            # If this is an AJAX request, return only the messages part
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return render(request, 'fitness/partials/chat_messages.html', context)

    return render(request, 'fitness/community.html', context)


@login_required
def send_message(request):
    """View to handle sending messages in the community"""
    if request.method == 'POST':
        message_text = request.POST.get('message')
        receiver_id = request.POST.get('receiver_id')

        if not message_text:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'Message cannot be empty'})
            messages.error(request, "Message cannot be empty")
            return redirect('community')

        try:
            receiver = User.objects.get(id=receiver_id)

            # Create and save the message
            message = CommunityMessage(
                sender=request.user,
                receiver=receiver,
                message=message_text
            )
            message.save()

            # If it's an AJAX request, return JSON response
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})

            # Otherwise redirect back to the conversation
            if request.user.is_superuser:
                return redirect(f'/community/?user_id={receiver_id}')
            else:
                return redirect('community')

        except User.DoesNotExist:
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'error', 'message': 'User not found'})
            messages.error(request, "User not found")
            return redirect('community')

    return redirect('community')


def fitness_view(request):
    """Landing page for the fitness app"""
    return render(request, 'fitness/fitness.html')


# Add this temporarily to test login functionality
def create_test_user():
    try:
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='your_test_password'
        )
        return "Test user created successfully"
    except Exception as e:
        return f"Error creating test user: {str(e)}"


@login_required
def get_diet_description(request):
    """Get AI-generated description of daily diet plan that's optimized for speech"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            # Create a prompt for OpenAI
            prompt = f"""
            You are a friendly AI nutritionist assistant for the AptiFit app. 
            Describe the following diet plan for {data['day']} in a conversational, encouraging way:
            
            Breakfast: {data['breakfast']} ({data['breakfast_calories']} calories)
            Lunch: {data['lunch']} ({data['lunch_calories']} calories)
            Dinner: {data['dinner']} ({data['dinner_calories']} calories)
            Snacks: {data['snacks']} ({data['snacks_calories']} calories)
            Total calories: {data['total_calories']}
            
            Important: Your response will be read aloud by a text-to-speech system, so:
            1. Use natural, conversational language with proper pauses (commas, periods)
            2. Keep your response under 100 words
            3. Be friendly and mention specific foods from the plan
            4. Give 1-2 quick health benefits of a key ingredient in the diet
            5. End with a brief motivational note
            """

            # Get API key from environment variable or settings
            api_key = os.environ.get(
                'OPENAI_API_KEY') or settings.OPENAI_API_KEY

            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o",  # Changed from gpt-3.5-turbo to gpt-4o
                messages=[
                    {"role": "system", "content": "You are a helpful fitness assistant that gives brief, friendly diet descriptions optimized for text-to-speech."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )

            message = response.choices[0].message.content.strip()

            return JsonResponse({'message': message})

        except Exception as e:
            return JsonResponse({
                'message': f"For {data['day']}, I've prepared a meal plan with {data['breakfast']} for breakfast, {data['lunch']} for lunch, and {data['dinner']} for dinner. Don't forget your snacks: {data['snacks']}. Your total calorie intake will be approximately {data['total_calories']} calories. Enjoy your meals and stay healthy!"
            })

    return JsonResponse({'message': 'Invalid request method'}, status=400)


@login_required
def get_exercise_description(request):
    """Get AI-generated description of exercise plan for a specific day"""
    if request.method == 'POST':
        try:
            data = json.loads(request.body)

            # Create a prompt for OpenAI
            prompt = f"""
            You are a friendly AI fitness trainer assistant for the AptiFit app. 
            Describe the following {data['fitness_level']} level exercise plan for {data['day_name']} in a motivational, encouraging way:
            
            Day: {data['day_title']}
            Warmup: {data['warmup']}
            Exercises: {data['exercises']}
            Cooldown: {data['cooldown']}
            
            Important: Your response will be read aloud by a text-to-speech system, so:
            1. Use natural, conversational language with proper pauses (commas, periods)
            2. Keep your response under 100 words
            3. Be enthusiastic and motivational like a personal trainer
            4. Mention 1-2 benefits of today's specific exercises
            5. Include a quick form tip for one of the exercises
            6. End with a brief motivational statement
            """

            # Get API key from environment variable or settings
            api_key = os.environ.get(
                'OPENAI_API_KEY') or settings.OPENAI_API_KEY

            client = openai.OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model="gpt-4o",  # Changed from gpt-3.5-turbo to gpt-4o
                messages=[
                    {"role": "system", "content": "You are a helpful fitness trainer that gives brief, motivational exercise descriptions optimized for text-to-speech."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=1000,
                temperature=0.7
            )

            message = response.choices[0].message.content.strip()

            return JsonResponse({'message': message})

        except Exception as e:
            return JsonResponse({
                'message': f"Today's workout focuses on {data['day_title']}. Start with {data['warmup']}, then perform exercises including {data['exercises']}. Remember to maintain proper form and control your breathing. Finish with {data['cooldown']} to help your muscles recover. You've got this!"
            })

    return JsonResponse({'message': 'Invalid request method'}, status=400)


@login_required
@require_POST
def process_speech_query(request):
    """Process a user's speech query with OpenAI GPT-4 for longer, more detailed responses"""
    try:
        data = json.loads(request.body)
        user_query = data.get('query', '')

        if not user_query:
            return JsonResponse({'success': False, 'message': 'Empty query'})

        logger.info(f"Processing speech query: {user_query[:30]}...")

        # Get API key from settings or environment
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            return JsonResponse({'success': False, 'message': 'OpenAI API key not configured'})

        # Call OpenAI API (GPT-4) with increased token count and modified prompt
        client = openai.OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                    "content": "You are a helpful fitness assistant speaking through a talking avatar. Provide detailed, informative responses related to fitness, nutrition, and health. Use natural language with proper pauses (commas, periods) since your response will be spoken aloud. Always include at least 3-4 sentences for a comprehensive answer."},
                {"role": "user", "content": user_query}
            ],
            max_tokens=500,  # Increased from 150 to 500 for longer responses
            temperature=0.7
        )

        ai_response = response.choices[0].message.content.strip()
        logger.info(f"Got response from OpenAI: {ai_response[:50]}...")

        return JsonResponse({
            'success': True,
            'response': ai_response
        })

    except Exception as e:
        logger.error(f"Error in process_speech_query: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@require_POST
def create_talking_avatar(request):
    """Create a talking avatar using D-ID API with optimized settings for production environments"""
    try:
        data = json.loads(request.body)
        message = data.get('message', '')

        if not message:
            return JsonResponse({'success': False, 'message': 'Empty message'})

        # Limit message length to improve processing speed
        if len(message) > 250:
            message = message[:250] + "..."

        logger.info(f"Creating talking avatar for message: {message[:30]}...")

        # Get D-ID credentials from environment variables
        username = os.environ.get('DID_API_USERNAME', '')
        password = os.environ.get('DID_API_PASSWORD', '')

        if not username or not password:
            return JsonResponse({'success': False, 'message': 'D-ID API credentials not configured'})

        # Encode credentials
        credentials = f"{username}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        # D-ID API endpoint
        url = "https://api.d-id.com/talks"

        # Payload for D-ID - with optimized settings for faster generation
        payload = {
            # Use a pre-optimized avatar for faster generation
            "source_url": "https://d-id-public-bucket.s3.us-west-2.amazonaws.com/alice.jpg",
            "script": {
                "type": "text",
                "subtitles": "false",
                "provider": {
                    "type": "microsoft",
                    "voice_id": "Sara"
                },
                "input": message,
                "ssml": "false"
            },
            "config": {
                "fluent": "false",
                "stitch": True,  # Use stitching for faster generation
                "result_format": "mp4"  # Use mp4 for better compatibility
            }
        }

        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Basic {encoded_credentials}"
        }

        # Call D-ID API with SSL verification disabled
        response = requests.post(
            url, json=payload, headers=headers, verify=False)
        response_data = response.json()

        logger.info(
            f"D-ID API initial response status: {response.status_code}")

        if response.status_code not in [201, 200]:
            error_msg = response_data.get('error', 'Unknown error')
            logger.error(f"D-ID API error: {error_msg}")
            return JsonResponse({
                'success': False,
                'message': f"D-ID API error: {error_msg}"
            })

        # Get the talk ID
        talk_id = response_data.get('id')
        logger.info(f"D-ID talk ID: {talk_id}")

        if not talk_id:
            return JsonResponse({
                'success': False,
                'message': 'No talk ID returned from D-ID'
            })

        # For production environments, don't wait for the video to complete processing
        # Instead, return the talk ID immediately and let the frontend poll for completion
        return JsonResponse({
            'success': True,
            'pending': True,
            'talk_id': talk_id,
            'message': 'Avatar generation started. Frontend will poll for completion.'
        })

    except Exception as e:
        logger.error(f"Error in create_talking_avatar: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })


@login_required
@require_POST
def check_avatar_status(request):
    """Check the status of a D-ID talking avatar generation"""
    try:
        data = json.loads(request.body)
        talk_id = data.get('talk_id')

        if not talk_id:
            return JsonResponse({'success': False, 'message': 'Missing talk ID'})

        # Get D-ID credentials from environment variables
        username = os.environ.get('DID_API_USERNAME', '')
        password = os.environ.get('DID_API_PASSWORD', '')

        if not username or not password:
            return JsonResponse({'success': False, 'message': 'D-ID API credentials not configured'})

        # Encode credentials
        credentials = f"{username}:{password}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        # Check status from D-ID API
        result_url = f"https://api.d-id.com/talks/{talk_id}"
        headers = {
            "accept": "application/json",
            "authorization": f"Basic {encoded_credentials}"
        }

        # Get result with SSL verification disabled
        result_response = requests.get(
            result_url, headers=headers, verify=False)

        if result_response.status_code != 200:
            return JsonResponse({
                'success': False,
                'message': f'Error checking status: {result_response.status_code}'
            })

        result_data = result_response.json()
        status = result_data.get('status')

        if status == 'done':
            video_url = result_data.get('result_url')
            if not video_url:
                return JsonResponse({
                    'success': False,
                    'message': 'No video URL in completed D-ID response'
                })

            return JsonResponse({
                'success': True,
                'completed': True,
                'video_url': video_url
            })
        elif status == 'error':
            error_msg = result_data.get('error', 'Unknown error')
            return JsonResponse({
                'success': False,
                'message': f'D-ID processing error: {error_msg}'
            })
        else:
            # Still processing
            return JsonResponse({
                'success': True,
                'completed': False,
                'status': status
            })

    except Exception as e:
        logger.error(f"Error in check_avatar_status: {str(e)}")
        return JsonResponse({
            'success': False,
            'message': str(e)
        })
