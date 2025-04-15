from django.urls import path
from . import views
from django.contrib.auth import views as auth_views

urlpatterns = [
    path("", views.fitness_view, name="fitness"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("index/", views.index, name="index"),
    path('profile/', views.profile, name='profile'),
    path('profile/save/', views.save_profile, name='save_profile'),
    path('profile/update/', views.update_profile, name='update_profile'),
    path('chatbot/', views.chatbot, name='chatbot'),
    path('logout/', views.logout_view, name='logout'),
    path('change-password/', views.change_password, name='change_password'),
    path('forget-password/', views.forget_password, name='forget_password'),
    path('reset-password/<str:token>/',
         views.reset_password, name='reset_password'),
    path('forget-password/', views.forget_password, name='forget_password'),
    path('reset-password/',
         auth_views.PasswordResetView.as_view(
             template_name='fitness/forgetpassword.html',
             email_template_name='fitness/password_reset_email.html',
             success_url='/reset-password-sent/'
         ),
         name='password_reset'),
    path('reset-password-sent/',
         auth_views.PasswordResetDoneView.as_view(
             template_name='fitness/password_reset_sent.html'
         ),
         name='password_reset_done'),
    path('reset-password/<str:uidb64>/<str:token>/',
         views.reset_password, name='password_reset_confirm'),
    path('reset-password-complete/',
         auth_views.PasswordResetCompleteView.as_view(
             template_name='fitness/password_reset_complete.html'
         ),
         name='password_reset_complete'),
    path('profile/save-notification/', views.save_notification_preference,
         name='save_notification_preference'),
    path('edit-diet/', views.edit_diet, name='edit_diet'),
    path('save-diet/', views.save_diet, name='save_diet'),
    path('diet-tracker/', views.diet_tracker, name='diet_tracker'),
    path('update-diet/', views.update_diet, name='update_diet'),
    path('exercise-tracker/', views.exercise_tracker, name='exercise_tracker'),
    path('view-exercise-plan/', views.view_exercise_plan,
         name='view_exercise_plan'),
    path('health-tracker/', views.health_tracker, name='health_tracker'),
    path('community/', views.community, name='community'),
    path('send-message/', views.send_message, name='send_message'),
    path('get-diet-description/', views.get_diet_description,
         name='get_diet_description'),
    path('get-exercise-description/', views.get_exercise_description,
         name='get_exercise_description'),
    path('api/process_speech_query/', views.process_speech_query,
         name='process_speech_query'),
    path('api/create_talking_avatar/', views.create_talking_avatar,
         name='create_talking_avatar'),
    path('api/check_avatar_status/', views.check_avatar_status,
         name='check_avatar_status'),
]
