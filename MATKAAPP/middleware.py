from django.contrib.sessions.models import Session
from django.shortcuts import redirect
from django.contrib.auth import logout
from django.contrib import messages
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db import transaction as db_transaction
import time

class DelayedWinningCreditMiddleware:
    """
    Task 11: Credits winning bets 30 minutes after result declaration.
    Checks for any PENDING or WIN bets that need crediting when user interacts.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            self.process_pending_winnings(request.user)
        
        response = self.get_response(request)
        return response

    def process_pending_winnings(self, user):
        from .models import Bet, Transaction
        
        # Get all WIN bets that haven't been credited yet
        uncredited_bets = Bet.objects.filter(
            user=user, 
            status='WIN', 
            is_credited=False
        ).select_related('market')

        now = timezone.now()
        delay = timedelta(minutes=30)

        for bet in uncredited_bets:
            market = bet.market
            # Determine which declaration time to use
            decl_time = None
            if bet.game_type == 'JODI':
                # Jodi needs both Open and Close
                if market.open_declared_at and market.close_declared_at:
                    decl_time = max(market.open_declared_at, market.close_declared_at)
            elif bet.session == 'OPEN':
                decl_time = market.open_declared_at
            else:
                decl_time = market.close_declared_at

            if decl_time and (now - decl_time) >= delay:
                with db_transaction.atomic():
                    # Double check if already credited (avoid race conditions)
                    bet_to_credit = Bet.objects.select_for_update().get(id=bet.id)
                    if not bet_to_credit.is_credited:
                        wallet = user.wallet
                        wallet.balance += Decimal(str(bet_to_credit.win_amount))
                        wallet.save()

                        Transaction.objects.create(
                            wallet=wallet,
                            amount=Decimal(str(bet_to_credit.win_amount)),
                            txn_type='WIN',
                            description=f"WIN: {bet_to_credit.game_type} - {market.name} ({bet_to_credit.number}) [30m Delayed]"
                        )

                        bet_to_credit.is_credited = True
                        bet_to_credit.credited_at = now
                        bet_to_credit.save()

                        # Notification (Task 14)
                        from .views import create_notification
                        create_notification(
                            user,
                            "Winning Credit Received",
                            f"Congratulations! ₹{bet_to_credit.win_amount} credited to your wallet for {market.name} ({bet_to_credit.game_type})."
                        )


class OneSessionPerUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            session_key = request.session.session_key
            try:
                profile = request.user.profile
                # Task 2: If the session key in profile doesn't match current session, logout
                if profile.session_key and profile.session_key != session_key:
                    from django.contrib.sessions.models import Session
                    # Optional: delete the old session from DB
                    Session.objects.filter(session_key=session_key).delete()
                    logout(request)
                    messages.error(request, "You have been logged out because your account was logged in from another device.")
                    return redirect('login')
                elif not profile.session_key and session_key:
                    profile.session_key = session_key
                    profile.save()
            except Exception:
                pass
        
        response = self.get_response(request)
        return response

class SessionTimeoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            current_time = time.time()
            last_activity = request.session.get('last_activity')

            if last_activity:
                elapsed_time = current_time - last_activity
                if elapsed_time > settings.SESSION_TIMEOUT_SECONDS:
                    logout(request)
                    messages.warning(request, "Session expired due to inactivity.")
                    return redirect('login')

            request.session['last_activity'] = current_time
        
        response = self.get_response(request)
        return response
