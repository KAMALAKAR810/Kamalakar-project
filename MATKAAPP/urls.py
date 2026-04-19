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
    path("admin-2fa/", views.admin_2fa_view, name="admin_2fa"),
    path("admin-security-settings/", views.update_admin_security_view, name="admin_security_settings"),
    path("api/biometric/reg-options/", views.biometric_reg_options, name="biometric_reg_options"),
    path("api/biometric/reg-verify/", views.biometric_reg_verify, name="biometric_reg_verify"),
    path("api/biometric/auth-options/", views.biometric_auth_options, name="biometric_auth_options"),
    path("api/biometric/auth-verify/", views.biometric_auth_verify, name="biometric_auth_verify"),

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
    path("admin-payments/", views.admin_payment_management, name="admin_payment_management"),
    path("admin-user-activity/", views.admin_user_activity, name="admin_user_activity"),
    path("delete-bet/<int:bet_id>/", views.delete_bet, name="delete_bet"),
    path("wallet/", views.wallet_view, name="wallet"),
    path("wallet-history/", views.wallet_history_view, name="wallet_history"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("admin-withdrawals/", views.admin_withdrawal_management, name="admin_withdrawal_management"),

    # --- History ---
    path("bet-history/", views.bet_history, name="bet_history"),
    path("jodi-winners/", views.jodi_winners_view, name="jodi_winners"),

    # --- Admin Views ---
    path("admin-summary/", views.admin_summary, name="admin_summary"),
    path("manage-markets/", views.manage_markets, name="manage_markets"),
    path("reset-market/<int:market_id>/", views.reset_market, name="reset_market"),
    path("market-history/", views.market_history_view, name="market_history"),
    path("market-bets/", views.market_bets, name="market_bets"),
    path("admin-bets/", views.admin_bet_history, name="admin_bet_history"),
    path("admin-report/", views.admin_report, name="admin_report"),
    path("organize-data/", views.organize_data_view, name="organize_data"),
    path("admin-declare/", views.declare_result, name="declare_result"),
    path("admin-winners/", views.winners_list, name="winners_list"),

    # --- Wallet REST Endpoints ---
    path("api/wallet/balance/", views.wallet_balance_api, name="wallet_balance_api"),
    path("api/wallet/history/", views.wallet_history_api, name="wallet_history_api"),
    path("api/admin/market-alerts/", views.admin_market_alerts, name="admin_market_alerts"),
]
