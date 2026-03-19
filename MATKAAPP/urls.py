from django.urls import path
from . import views
from .views import WalletBalanceView, TransactionHistoryView

urlpatterns = [
    path("", views.index, name="index"),
    path("error/", views.error, name="error"),
    path("display/", views.display, name="display"),
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("single/", views.single, name="single"),
    path("jodi/", views.jodi, name="jodi"),
    path("single_pathi/", views.single_pathi, name="single_pathi"),
    path("api/place-bet/", views.place_bet, name="place_bet"), # Add this line
    path("bet-history/", views.bet_history, name="bet_history"),
    path('admin-summary/', views.admin_summary, name='admin_summary'),
    path('declare-result/', views.declare_result, name='declare_result'),
     path('balance/', WalletBalanceView.as_view(), name='wallet-balance'),
    path('history/', TransactionHistoryView.as_view(), name='transaction-history'),
    path("double_pathi/", views.double_pathi, name="double_pathi"),
    path("tripple_pathi/", views.tripple_pathi, name="tripple_pathi"),
    # --- Wallet API Endpoints ---
    path("api/wallet/balance/", views.wallet_balance_api, name="wallet_balance_api"),
    path("api/wallet/history/", views.wallet_history_api, name="wallet_history_api"),
]