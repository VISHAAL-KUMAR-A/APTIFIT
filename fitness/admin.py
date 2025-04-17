from django.contrib import admin
from .models import UserProfile, DietPlan, DailyDietPlan, ExercisePlan, ExerciseDay, Exercise, ExerciseTip, ExercisePrecaution, HealthData, CommunityMessage, Thread, Message, UserSetting

# Register your models here.
admin.site.register(UserProfile)
admin.site.register(DietPlan)
admin.site.register(DailyDietPlan)
admin.site.register(ExercisePlan)
admin.site.register(ExerciseDay)
admin.site.register(Exercise)
admin.site.register(ExerciseTip)
admin.site.register(ExercisePrecaution)
admin.site.register(HealthData)
admin.site.register(CommunityMessage)
admin.site.register(UserSetting)


class MessageInline(admin.StackedInline):
    model = Message
    fields = ('sender', 'text', 'isread')
    readonly_fields = ('sender', 'text', 'isread')


class ThreadAdmin(admin.ModelAdmin):
    model = Thread
    inlines = (MessageInline,)


admin.site.register(Thread, ThreadAdmin)
