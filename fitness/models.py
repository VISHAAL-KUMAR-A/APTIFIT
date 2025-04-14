from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# Create your models here.


class UserProfile(models.Model):
    NOTIFICATION_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('none', 'None'),
    ]

    DIET_CHOICES = [
        ('vegetarian', 'Vegetarian'),
        ('non-vegetarian', 'Non-Vegetarian'),
    ]

    ETHNIC_GROUP_CHOICES = [
        ('asian', 'Asian'),
        ('black', 'Black/African'),
        ('hispanic', 'Hispanic/Latino'),
        ('middle_eastern', 'Middle Eastern'),
        ('white', 'White/Caucasian'),
        ('pacific_islander', 'Pacific Islander'),
        ('native_american', 'Native American'),
        ('mixed', 'Mixed Ethnicity'),
        ('other', 'Other'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    last_password_change = models.DateTimeField(auto_now=True)
    phone_number = models.CharField(max_length=15, blank=True, null=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)

    # Fitness profile data
    height = models.FloatField(blank=True, null=True)  # in cm
    weight = models.FloatField(blank=True, null=True)  # in kg
    sex = models.CharField(max_length=10, blank=True, null=True)
    age = models.IntegerField(blank=True, null=True)  # add age field

    # New cultural and dietary preference fields
    country = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    language = models.CharField(max_length=100, blank=True, null=True)
    ethnic_group = models.CharField(
        max_length=20,
        choices=ETHNIC_GROUP_CHOICES,
        blank=True,
        null=True
    )
    diet_preference = models.CharField(
        max_length=20,
        choices=DIET_CHOICES,
        blank=True,
        null=True
    )

    # Notification preferences
    notification_preference = models.CharField(
        max_length=10,
        choices=NOTIFICATION_CHOICES,
        default='none'
    )

    def __str__(self):
        return self.user.username

    def update_user_info(self, username=None, email=None):
        if username:
            self.user.username = username
        if email:
            self.user.email = email
        self.user.save()

    @property
    def bmi(self):
        if self.height and self.weight:
            height_m = self.height / 100
            return round(self.weight / (height_m * height_m), 1)
        return None

    @property
    def bmi_category(self):
        bmi = self.bmi
        if bmi is None:
            return None
        elif bmi < 18.5:
            return "Underweight"
        elif bmi < 25:
            return "Normal weight"
        elif bmi < 30:
            return "Overweight"
        else:
            return "Obese"

    @property
    def body_fat(self):
        bmi = self.bmi
        if bmi is None or not self.sex or not self.age:
            return None

        # Using U.S. Navy method estimation with actual age
        if self.sex.lower() == "male":
            return round(1.20 * bmi + 0.23 * self.age - 10.8 * 1 - 5.4, 1)
        else:
            return round(1.20 * bmi + 0.23 * self.age - 10.8 * 0 - 5.4, 1)

    @property
    def body_fat_category(self):
        bf = self.body_fat
        if bf is None or not self.sex:
            return None

        if self.sex.lower() == "male":
            if bf < 10:
                return "Essential fat"
            elif bf < 14:
                return "Athletes"
            elif bf < 21:
                return "Fitness"
            elif bf < 25:
                return "Average"
            else:
                return "Obese"
        else:
            if bf < 14:
                return "Essential fat"
            elif bf < 21:
                return "Athletes"
            elif bf < 25:
                return "Fitness"
            elif bf < 32:
                return "Average"
            else:
                return "Obese"

    @property
    def daily_calorie_needs(self):
        """Calculate daily calorie needs using Mifflin-St Jeor Equation with activity factor"""
        if not self.height or not self.weight or not self.sex or not self.age:
            return None

        # Calculate BMR using Mifflin-St Jeor Equation
        if self.sex.lower() == 'male':
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age + 5
        else:
            bmr = 10 * self.weight + 6.25 * self.height - 5 * self.age - 161

        # Apply activity factor (default to moderate activity)
        activity_factor = 1.55  # Moderate exercise (3-5 days/week)

        return int(bmr * activity_factor)


class DietPlan(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # This will store whether the user has a diet plan at all
    has_diet_plan = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.user.username}'s Diet Plan"

    def get_day_plan(self, day_of_week):
        """Get the diet plan for a specific day of the week"""
        try:
            return self.daily_plans.get(day_of_week=day_of_week.lower())
        except DailyDietPlan.DoesNotExist:
            return None


class DailyDietPlan(models.Model):
    DAYS_OF_WEEK = [
        ('monday', 'Monday'),
        ('tuesday', 'Tuesday'),
        ('wednesday', 'Wednesday'),
        ('thursday', 'Thursday'),
        ('friday', 'Friday'),
        ('saturday', 'Saturday'),
        ('sunday', 'Sunday'),
    ]

    diet_plan = models.ForeignKey(
        DietPlan, related_name='daily_plans', on_delete=models.CASCADE)
    day_of_week = models.CharField(max_length=10, choices=DAYS_OF_WEEK)
    breakfast = models.TextField(blank=True, null=True)
    breakfast_calories = models.IntegerField(blank=True, null=True)
    lunch = models.TextField(blank=True, null=True)
    lunch_calories = models.IntegerField(blank=True, null=True)
    dinner = models.TextField(blank=True, null=True)
    dinner_calories = models.IntegerField(blank=True, null=True)
    snacks = models.TextField(blank=True, null=True)
    snacks_calories = models.IntegerField(blank=True, null=True)

    class Meta:
        unique_together = ['diet_plan', 'day_of_week']

    @property
    def total_calories(self):
        total = 0
        if self.breakfast_calories:
            total += self.breakfast_calories
        if self.lunch_calories:
            total += self.lunch_calories
        if self.dinner_calories:
            total += self.dinner_calories
        if self.snacks_calories:
            total += self.snacks_calories
        return total if total > 0 else None

    def __str__(self):
        return f"{self.diet_plan.user.username}'s {self.get_day_of_week_display()} Diet"


class ExercisePlan(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    # beginner, intermediate, advanced
    fitness_level = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username}'s {self.fitness_level.title()} Exercise Plan"


class ExerciseDay(models.Model):
    exercise_plan = models.ForeignKey(
        ExercisePlan, related_name='days', on_delete=models.CASCADE)
    day = models.CharField(max_length=20)  # Monday, Tuesday, etc.
    focus = models.CharField(max_length=100)  # Chest & Triceps, Legs, etc.
    warmup = models.TextField()
    cooldown = models.TextField()
    duration = models.CharField(max_length=50)

    def __str__(self):
        return f"{self.day}: {self.focus}"


class Exercise(models.Model):
    exercise_day = models.ForeignKey(
        ExerciseDay, related_name='exercises', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    sets = models.IntegerField()
    reps = models.CharField(max_length=20)
    rest = models.CharField(max_length=20)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.name


class ExerciseTip(models.Model):
    exercise_plan = models.ForeignKey(
        ExercisePlan, related_name='tips', on_delete=models.CASCADE)
    text = models.TextField()

    def __str__(self):
        return self.text[:50]


class ExercisePrecaution(models.Model):
    exercise_plan = models.ForeignKey(
        ExercisePlan, related_name='precautions', on_delete=models.CASCADE)
    text = models.TextField()

    def __str__(self):
        return self.text[:50]


class HealthData(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='health_data')
    date = models.DateTimeField(auto_now_add=True)
    heart_rate = models.IntegerField(null=True, blank=True)
    steps = models.IntegerField(null=True, blank=True)
    calories_burnt = models.IntegerField(null=True, blank=True)
    sleep_hours = models.FloatField(null=True, blank=True)
    blood_pressure = models.CharField(max_length=20, null=True, blank=True)
    oxygen_level = models.IntegerField(null=True, blank=True)
    additional_data = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.user.username}'s health data on {self.date.strftime('%Y-%m-%d')}"

    @property
    def heart_rate_status(self):
        if not self.heart_rate:
            return "Unknown"
        if self.heart_rate < 60:
            return "Low"
        elif self.heart_rate <= 100:
            return "Normal"
        else:
            return "Elevated"

    @property
    def steps_status(self):
        if not self.steps:
            return "Unknown"
        if self.steps < 5000:
            return "Low"
        elif self.steps < 10000:
            return "Moderate"
        else:
            return "Excellent"

    @property
    def sleep_status(self):
        if not self.sleep_hours:
            return "Unknown"
        if self.sleep_hours < 6:
            return "Insufficient"
        elif self.sleep_hours <= 9:
            return "Optimal"
        else:
            return "Excessive"

    @property
    def o2_status(self):
        if not self.oxygen_level:
            return "Unknown"
        if self.oxygen_level < 90:
            return "Low"
        elif self.oxygen_level < 95:
            return "Borderline"
        else:
            return "Normal"


class CommunityMessage(models.Model):
    sender = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='sent_messages')
    receiver = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='received_messages', null=True, blank=True)
    message = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    is_read = models.BooleanField(default=False)

    def __str__(self):
        if self.receiver:
            return f"Message from {self.sender.username} to {self.receiver.username}"
        else:
            return f"Message from {self.sender.username} to all users"

    class Meta:
        ordering = ['-timestamp']


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    instance.userprofile.save()
