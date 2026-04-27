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

class SecurityHeadersMiddleware:
    """
    Adds baseline security headers consistently (including error responses).
    Django's SecurityMiddleware covers many of these, but scanners often flag
    missing headers when upstream/proxy config varies. This keeps them uniform.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Prevent MIME sniffing
        response.setdefault("X-Content-Type-Options", "nosniff")

        # Clickjacking protection (also set via settings, but ensure present)
        response.setdefault("X-Frame-Options", "DENY")

        # Legacy XSS header (deprecated in modern browsers, but helps scanners)
        response.setdefault("X-XSS-Protection", "0")

        # Reduce referrer leakage
        response.setdefault("Referrer-Policy", "same-origin")

        # Basic permissions policy (avoid sensitive APIs)
        response.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )

        # Tighten caching for auth endpoints (helps avoid auth leaks)
        if request.path.startswith("/login") or request.path.startswith("/register") or request.path.startswith("/verify-email"):
            response.setdefault("Cache-Control", "no-store")
            response.setdefault("Pragma", "no-cache")

        return response

class ContentSecurityPolicyMiddleware:
    """
    Adds a CSP header to reduce XSS risk.
    Note: this project uses inline <script>/<style>, so we allow 'unsafe-inline'.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Don't override if already set by upstream.
        if response.get("Content-Security-Policy"):
            return response

        # Allow required CDNs and Google reCAPTCHA.
        csp_parts = [
            "default-src 'self'",
            "base-uri 'self'",
            "object-src 'none'",
            "frame-ancestors 'self'",
            "form-action 'self'",
            "img-src 'self' data: https:",
            "font-src 'self' https://cdnjs.cloudflare.com data:",
            "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com",
            "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://www.google.com https://www.gstatic.com",
            "connect-src 'self' https:",
            "frame-src https://www.google.com",
        ]

        # In production, prefer upgrading any http subresources.
        if not settings.DEBUG:
            csp_parts.append("upgrade-insecure-requests")

        response["Content-Security-Policy"] = "; ".join(csp_parts)
        response["Referrer-Policy"] = response.get("Referrer-Policy", "same-origin")
        response["Permissions-Policy"] = response.get("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

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
                    # Task 2: Delete the old session from DB
                    Session.objects.filter(session_key=profile.session_key).delete()
                    logout(request)
                    messages.error(request, "You have been logged out because your account was logged in from another device.")
                    return redirect('login')
                elif not profile.session_key and session_key:
                    profile.session_key = session_key
                    profile.save()
            except:
                pass
        
        response = self.get_response(request)
        return response

class Admin2FAMiddleware:
    """
    Ensures that admins must complete a second factor authentication
    before accessing admin areas.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only check for staff/superusers
        if request.user.is_authenticated and request.user.is_staff:
            # Paths that require 2FA
            # Django admin is now 'secure-admin-5266'
            is_admin_path = request.path.startswith('/secure-admin-5266/') or request.path.startswith('/admin-')
            
            # Paths that ARE the 2FA verification itself (avoid loops)
            is_2fa_path = request.path == '/admin-2fa/'
            
            if is_admin_path and not is_2fa_path:
                if not request.session.get('admin_2fa_verified'):
                    return redirect('admin_2fa')
        
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
