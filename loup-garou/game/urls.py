from django.urls import path

from . import views

app_name = 'game'

urlpatterns = [
    path('', views.village_view, name='village'),
    path('partie/nouvelle', views.new_game_view, name='new_game'),
    path('partie/quitter', views.leave_game_view, name='leave_game'),
    path('confidentialite', views.privacy_view, name='privacy'),
    path('confidentialite/supprimer', views.delete_data_view, name='delete_data'),
    path('api/partie/etat', views.state_view, name='api_state'),
    path('api/partie/message', views.message_view, name='api_message'),
    path('api/partie/vote', views.vote_view, name='api_vote'),
    path('api/partie/nuit', views.night_view, name='api_night'),
]
