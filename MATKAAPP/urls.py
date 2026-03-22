from django.urls import path
from . import views

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

    # --- Chat & User Messaging ---
    path("chat/", views.chat_view, name="chat"),
    path("chat/<int:user_id>/", views.chat_view, name="admin_chat_user"),
    path("admin-users/", views.admin_user_management, name="admin_user_management"),
    path("admin-chats/", views.admin_chat_list, name="admin_chat_list"),
    path("api/send-welcome/<int:user_id>/", views.send_welcome_msg, name="send_welcome_msg"),

    # --- Payment ---
    path("payment/", views.payment_page, name="payment"),

    # --- History ---
    path("bet-history/", views.bet_history, name="bet_history"),

    # --- Admin Views ---
    path("admin-summary/", views.admin_summary, name="admin_summary"),
    path("manage-markets/", views.manage_markets, name="manage_markets"),
    path("market-bets/", views.market_bets, name="market_bets"),
    path("admin-bets/", views.admin_bet_history, name="admin_bet_history"),
    path("organize-data/", views.organize_data_view, name="organize_data"),
    path("admin-declare/", views.declare_result, name="declare_result"),
    path("admin-winners/", views.winners_list, name="winners_list"),

    # --- Wallet REST Endpoints ---
    path("api/wallet/balance/", views.wallet_balance_api, name="wallet_balance_api"),
    path("api/wallet/history/", views.wallet_history_api, name="wallet_history_api"),
]
