from django.urls import path
from . import views
from .views import WalletBalanceView, TransactionHistoryView

urlpatterns = [
    # --- Public Pages ---
    path("", views.index, name="index"),
    path("display/", views.display, name="display"),
    path("error/", views.error, name="error"),

    # --- Auth ---
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),

    # --- Game Pages ---
    path("single/", views.single, name="single"),
    path("jodi/", views.jodi, name="jodi"),
    path("single_pathi/", views.single_pathi, name="single_pathi"),
    path("double_pathi/", views.double_pathi, name="double_pathi"),
    path("tripple_pathi/", views.tripple_pathi, name="tripple_pathi"),

    # --- Bet API ---
    path("api/place-bet/", views.place_bet, name="place_bet"),

    # --- History ---
    path("bet-history/", views.bet_history, name="bet_history"),

    # --- Admin Views ---
    path("admin-summary/", views.admin_summary, name="admin_summary"),
    path("manage-markets/", views.manage_markets, name="manage_markets"),
    path("market-bets/", views.market_bets, name="market_bets"),

    # --- Wallet REST Endpoints ---
    path("api/wallet/balance/", views.wallet_balance_api, name="wallet_balance_api"),
    path("api/wallet/history/", views.wallet_history_api, name="wallet_history_api"),

    # --- DRF Class-Based Views ---
    path("balance/", WalletBalanceView.as_view(), name="wallet-balance"),
    path("history/", TransactionHistoryView.as_view(), name="transaction-history"),
]
