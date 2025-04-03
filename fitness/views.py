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
from fitness.models import DietPlan, DailyDietPlan
import re

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

    # Calculate daily calories if profile data exists
    daily_calories = None
    if user_profile.height and user_profile.weight and user_profile.sex:
        # Simple BMR calculation using Mifflin-St Jeor Equation
        weight = user_profile.weight  # kg
        height = user_profile.height  # cm
        age = 35  # default age if not available

        if user_profile.sex.lower() == 'male':
            bmr = 10 * weight + 6.25 * height - 5 * age + 5
        else:
            bmr = 10 * weight + 6.25 * height - 5 * age - 161

        # Assuming moderate activity level (1.55 multiplier)
        daily_calories = int(bmr * 1.55)

    # Check if user should see notifications based on preferences
    show_notification = False
    notification_message = ""

    if user_profile.notification_preference != 'none':
        today = datetime.datetime.now()

        if user_profile.notification_preference == 'daily':
            # Show notification every day
            show_notification = True
            notification_message = f"Remember to follow your {today.strftime('%A')} diet plan!"
        elif user_profile.notification_preference == 'weekly' and today.weekday() == 0:  # Monday
            # Show notification only on Mondays for weekly preference
            show_notification = True
            notification_message = "Here's your weekly diet plan reminder!"

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
        'has_notifications': show_notification,
        'notification_message': notification_message,
    }

    return render(request, 'fitness/index.html', context)


@login_required
def profile(request):
    user_profile = request.user.userprofile
    user_has_data = bool(
        user_profile.height and user_profile.weight and user_profile.sex)

    context = {
        'user_has_data': user_has_data,
        'notification_preference': user_profile.notification_preference,
    }

    if user_has_data:
        context.update({
            'height': user_profile.height,
            'weight': user_profile.weight,
            'sex': user_profile.sex,
            'bmi': user_profile.bmi,
            'bmi_category': user_profile.bmi_category,
            'body_fat': user_profile.body_fat,
            'body_fat_category': user_profile.body_fat_category,
        })

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
            client = openai.OpenAI(api_key=openai_api_key)

            # Prepare messages list
            messages = [{"role": "system", "content": system_message}]

            # If it's a diet plan request, include user profile data
            if is_diet_plan_request:
                user_profile = request.user.userprofile

                # Only proceed if user has completed their profile
                if user_profile.height and user_profile.weight and user_profile.sex:
                    profile_data = f"""
                    User Profile Data:
                    - Height: {user_profile.height} cm
                    - Weight: {user_profile.weight} kg
                    - Sex: {user_profile.sex}
                    - BMI: {user_profile.bmi} ({user_profile.bmi_category})
                    - Body Fat: {user_profile.body_fat}% ({user_profile.body_fat_category})
                    
                    Based on this profile data, create a weekly meal plan (Monday through Sunday) 
                    with different meals for each day. For each day, include:
                    
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
                    The meal plan should be appropriate for their BMI and body composition.
                    Start your response with "Here's your personalized weekly diet plan:"
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
                max_tokens=500,
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
        # Get form data
        try:
            height = float(request.POST.get('height'))
            weight = float(request.POST.get('weight'))
            sex = request.POST.get('sex')

            # Save to user profile
            user_profile = request.user.userprofile
            user_profile.height = height
            user_profile.weight = weight
            user_profile.sex = sex
            user_profile.save()

            messages.success(request, "Your fitness profile has been updated!")
        except (ValueError, TypeError):
            messages.error(
                request, "Invalid data provided. Please check your inputs.")

        return redirect('profile')

    return redirect('profile')


@login_required
def update_profile(request):
    user_profile = request.user.userprofile

    # Pre-fill the form with existing data
    context = {
        'user_has_data': False,  # Show form instead of data
        'height': user_profile.height,
        'weight': user_profile.weight,
        'sex': user_profile.sex,
    }

    return render(request, 'fitness/profile.html', context)


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
