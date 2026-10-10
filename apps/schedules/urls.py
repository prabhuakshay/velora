from django.urls import path

from apps.schedules import views

urlpatterns = [
    path("schedules/", views.schedule_list, name="schedule_list"),
    path("schedules/new/", views.schedule_create, name="schedule_create"),
    path("schedules/split-row/", views.schedule_split_row, name="schedule_split_row"),
    path("schedules/<int:pk>/", views.schedule_detail, name="schedule_detail"),
    path("schedules/<int:pk>/edit/", views.schedule_edit, name="schedule_edit"),
    path("schedules/<int:pk>/pause/", views.schedule_pause, name="schedule_pause"),
    path("schedules/<int:pk>/resume/", views.schedule_resume, name="schedule_resume"),
    path("schedules/<int:pk>/end/", views.schedule_end, name="schedule_end"),
]
