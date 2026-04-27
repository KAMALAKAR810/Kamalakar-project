from django.urls import path
from . import views
from .security_txt import security_txt

urlpatterns = [
    path(".well-known/security.txt", security_txt, name="security_txt"),
    # --- Public Pages ---
    path("", views.user_home, name="user_home"),
    path("admin-home/", views.admin_home, name="admin_home"),
    path("display/", views.display, name="display"),
    path("error/", views.error, name="error"),

    # --- Auth ---
    path("login/", views.login_view, name="login"),
    path("register/", views.register_view, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("admin-2fa/", views.admin_2fa_view, name="admin_2fa"),
    path("admin-security-settings/", views.update_admin_security_view, name="admin_security_settings"),
    path("verify-email/", views.verify_email_otp_view, name="verify_email_otp"),
    path("resend-email-otp/", views.resend_email_otp_view, name="resend_email_otp"),
    path("otp-result/", views.otp_result_view, name="otp_result"),

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
    path("admin-chat-user/<int:user_id>/", views.chat_view, name="admin_chat_user"),
    path("admin-user-management/", views.admin_user_management, name="admin_user_management"),
    path("admin-chat-list/", views.admin_chat_list, name="admin_chat_list"),
    path("api/send-welcome/<int:user_id>/", views.send_welcome_msg, name="send_welcome_msg"),

    # --- Payment ---
    path("payment/", views.payment_page, name="payment"),
    path("admin-payment-management/", views.admin_payment_management, name="admin_payment_management"),
    path("admin-user-activity/", views.admin_user_activity, name="admin_user_activity"),
    path("delete-bet/<int:bet_id>/", views.delete_bet, name="delete_bet"),
    path("wallet/", views.wallet_view, name="wallet"),
    path("wallet-history/", views.wallet_history_view, name="wallet_history"),
    path("notifications/", views.notifications_view, name="notifications"),
    path("admin-withdrawal-management/", views.admin_withdrawal_management, name="admin_withdrawal_management"),

    # --- History ---
    path("bet-history/", views.bet_history, name="bet_history"),

    # --- Admin Pages ---
    path("admin-summary/", views.admin_summary, name="admin_summary"),
    path("admin-manage-markets/", views.manage_markets, name="manage_markets"),
    path("admin-reset-market/<int:market_id>/", views.reset_market, name="reset_market"),
    path("admin-market-history/", views.market_history_view, name="market_history"),
    path("admin-market-bets/", views.market_bets, name="market_bets"),
    path("admin-bets/", views.admin_bet_history, name="admin_bet_history"),
    path("admin-jodi-winners/", views.jodi_winners_view, name="jodi_winners"),
    path("admin-report/", views.admin_report, name="admin_report"),
    path("admin-export-users/", views.export_user_data, name="export_user_data"),
    path("admin-organize-data/", views.organize_data_view, name="organize_data"),
    path("admin-declare-result/", views.declare_result, name="declare_result"),
    path("admin-winners-list/", views.winners_list, name="winners_list"),
    path("admin-market-alerts/", views.admin_market_alerts, name="admin_market_alerts"),

    # --- Wallet REST Endpoints ---
    path("api/wallet/balance/", views.wallet_balance_api, name="wallet_balance_api"),
    path("api/wallet/history/", views.wallet_history_api, name="wallet_history_api"),
]
