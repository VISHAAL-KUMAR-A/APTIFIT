# Generated by Django 5.2 on 2025-04-08 19:19

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('fitness', '0012_dailydietplan_breakfast_carbs_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dailydietplan',
            name='breakfast_carbs',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='breakfast_fat',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='breakfast_protein',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='dinner_carbs',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='dinner_fat',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='dinner_protein',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='lunch_carbs',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='lunch_fat',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='lunch_protein',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='snacks_carbs',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='snacks_fat',
        ),
        migrations.RemoveField(
            model_name='dailydietplan',
            name='snacks_protein',
        ),
    ]
