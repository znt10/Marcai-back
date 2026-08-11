from django.urls import path
from tenant import views

urlpatterns = [path("api/saude", views.saude, name="saude")]
