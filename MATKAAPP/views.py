from datetime import datetime, timedelta
from decimal import Decimal
import json
import logging
import os
import re
import hashlib

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
# FIX: Renamed import to 'db_transaction' to avoid name collision with the
# local variable 'transaction' used inside place_bet and the Transaction model.
from django.db import transaction as db_transaction
from django.db.models import Sum, Q, Count, Max
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import csrf_exempt
import requests
from django.conf import settings
from django_ratelimit.decorators import ratelimit
from django.contrib.auth.hashers import make_password, check_password
import secrets

from .models import Bet, Transaction, Market, Wallet, Profile, EmailOTP, Message, WithdrawalRequest, Notification, MarketHistory, PaymentSettings, DepositRequest, UserActivity, UserDeviceSession

logger = logging.getLogger(__name__)
DEVICE_ID_COOKIE_NAME = "clwn_device_id"


@login_required
def admin_2fa_view(request):
    if not request.user.is_staff:
        return redirect('user_home')
    
    if request.session.get('admin_2fa_verified'):
        return redirect('admin_summary')
    
    profile = request.user.profile
    
    if request.method == 'POST':
        auth_type = request.POST.get('auth_type')
        
        if auth_type == 'pin':
            pin = request.POST.get('pin')
            if pin == profile.admin_pin:
                request.session['admin_2fa_verified'] = True
                messages.success(request, "2FA Verified successfully!")
                return redirect('admin_summary')
            else:
                messages.error(request, "Invalid PIN!")
        
        elif auth_type == 'security_question':
            answer = request.POST.get('answer', '').strip()
            if answer == profile.admin_security_answer:
                request.session['admin_2fa_verified'] = True
                messages.success(request, "2FA Verified successfully!")
                return redirect('admin_summary')
            else:
                messages.error(request, "Incorrect answer!")
            
    return render(request, 'auth/admin_2fa.html', {
        'profile': profile,
        'page_title': 'Admin 2FA Verification'
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def update_admin_security_view(request):
    profile = request.user.profile
    if request.method == 'POST':
        new_pin = request.POST.get('admin_pin')
        new_question = request.POST.get('admin_security_question')
        new_answer = request.POST.get('admin_security_answer')
        support_whatsapp_number = re.sub(r"\D", "", request.POST.get('support_whatsapp_number', ''))
        
        if new_pin and len(new_pin) == 6 and new_pin.isdigit():
            profile.admin_pin = new_pin
        
        if new_question:
            profile.admin_security_question = new_question
            
        if new_answer:
            profile.admin_security_answer = new_answer

        profile.support_whatsapp_number = support_whatsapp_number
            
        profile.save()
        messages.success(request, "Security settings updated successfully!")
        return redirect('admin_summary')
        
    return render(request, 'auth/update_admin_security.html', {
        'profile': profile,
        'page_title': 'Update Admin Security'
    })

def create_notification(user, title, message):
    Notification.objects.create(user=user, title=title, message=message)

@login_required
def notifications_view(request):
    notifications = request.user.notifications.all()
    # Mark all as read when viewing
    notifications.filter(is_read=False).update(is_read=True)
    return render(request, 'user/notifications.html', {
        'notifications': notifications,
        'page_title': 'My Notifications'
    })

@login_required
def wallet_view(request):
    """User can convert game coins to INR and request withdrawal."""
    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))
        upi_id = request.POST.get('upi_id', '').strip()
        mobile_number = request.POST.get('mobile_number', '').strip()
        bank_account = request.POST.get('bank_account', '').strip()
        bank_name = request.POST.get('bank_name', '').strip()
        bank_holder_name = request.POST.get('bank_holder_name', '').strip()
        
        # Validation: At least two fields are mandatory, but Bank Holder Name is strictly required
        if not bank_holder_name:
            messages.error(request, "Name as per Bank is mandatory for withdrawal.")
            return redirect('wallet')

        provided_fields = [upi_id, mobile_number, bank_account]
        count_provided = sum(1 for field in provided_fields if field)
        
        if count_provided < 1:
            messages.error(request, "Please provide at least one additional detail (UPI ID, Mobile Number, or Bank Account) along with your Bank Holder Name.")
            return redirect('wallet')

        if amount < 300:
            messages.error(request, "Minimum withdrawal amount is ₹300.")
            return redirect('wallet')
        
        if amount > 50000:
            messages.error(request, "Maximum withdrawal amount is ₹50000.")
            return redirect('wallet')

        # Limit withdrawal to 3 times per day per user
        from django.utils import timezone
        today = timezone.now().date()
        daily_count = WithdrawalRequest.objects.filter(
            user=request.user, 
            created_at__date=today
        ).count()
        
        if daily_count >= 3:
            messages.error(request, "You have reached your daily withdrawal limit of 3 times per day.")
            return redirect('wallet')
            
        wallet = request.user.wallet
        if wallet.balance < amount:
            messages.error(request, "Insufficient balance!")
            return redirect('wallet')
            
        with db_transaction.atomic():
            wallet.balance -= amount
            wallet.save()
            
            WithdrawalRequest.objects.create(
                user=request.user,
                amount=amount,
                upi_id=upi_id,
                mobile_number=mobile_number,
                bank_account=bank_account,
                bank_name=bank_name,
                bank_holder_name=bank_holder_name
            )
            
            Transaction.objects.create(
                wallet=wallet,
                amount=amount,
                txn_type='WITHDRAWAL',
                description=f"Withdrawal Request: {upi_id or mobile_number or bank_account}"
            )
            
            # Notification (Task 14)
            create_notification(
                request.user,
                "Withdrawal Requested",
                f"Your request for ₹{amount} has been submitted."
            )

        # Notify admin on Telegram (outside atomic block — non-critical)
        send_telegram_message(
            f"🏧 <b>New Withdrawal Request</b>\n"
            f"👤 User: <b>{request.user.username}</b>\n"
            f"💵 Amount: <b>₹{amount}</b>\n"
            f"🏦 UPI/Account: <code>{upi_id or mobile_number or bank_account or 'N/A'}</code>\n"
            f"👨‍💼 Name: {bank_holder_name}\n"
            f"⏰ Time: {timezone.localtime().strftime('%d %b %Y, %I:%M %p')}"
        )

        messages.success(request, f"Withdrawal request for ₹{amount} submitted!")
        return redirect('wallet_history')
        
    return render(request, 'user/wallet.html', {
        'page_title': 'My Wallet & Withdraw'
    })


@login_required
def wallet_history_view(request):
    """User can see their wallet transactions and withdrawal status."""
    transactions = Transaction.objects.filter(wallet=request.user.wallet).order_by('-created_at')
    withdrawals = WithdrawalRequest.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'user/wallet_history.html', {
        'transactions': transactions,
        'withdrawals': withdrawals
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_withdrawal_management(request):
    """Admin manages withdrawal requests and updates status."""
    if request.method == 'POST':
        req_id = request.POST.get('request_id')
        new_status = request.POST.get('status')
        
        try:
            withdrawal = WithdrawalRequest.objects.get(id=req_id)
            old_status = withdrawal.status
            withdrawal.status = new_status
            withdrawal.save()
            
            # Notification (Task 14)
            create_notification(
                withdrawal.user,
                f"Withdrawal {new_status}",
                f"Your withdrawal request for ₹{withdrawal.amount} has been {new_status.lower()}."
            )
            
            # Task 13: Automatic message to user on status change
            admin_user = User.objects.filter(is_superuser=True).first()
            if admin_user and old_status != new_status:
                msg_content = f"Your withdrawal request of ₹{withdrawal.amount} has been {new_status}."
                Message.objects.create(
                    sender=admin_user,
                    receiver=withdrawal.user,
                    content=msg_content
                )
            
            messages.success(request, f"Withdrawal request {new_status} successfully!")
        except WithdrawalRequest.DoesNotExist:
            messages.error(request, "Request not found.")
            
        return redirect('admin_withdrawal_management')
        
    requests = WithdrawalRequest.objects.all().order_by('-created_at')
    return render(request, 'admin/admin_withdrawal_management.html', {'withdrawal_requests': requests})

def _markets_betting_payload():
    """Per-market OPEN/CLOSE windows for UI locks (matches Market.is_betting_allowed)."""
    return [
        {
            "id": m.id,
            "name": m.name,
            "open": m.is_betting_allowed("OPEN"),
            "close": m.is_betting_allowed("CLOSE"),
        }
        for m in Market.objects.all()
    ]


# --- PATTI NUMBER GROUPS ---

SINGLE_PATTI_GROUPS = {
    "1": ["128","137","146","236","245","290","380","470","489","560","678","579"],
    "2": ["129","138","147","156","237","246","345","390","480","570","679","589"],
    "3": ["120","139","148","157","238","247","256","346","490","580","670","689"],
    "4": ["130","149","158","167","239","248","257","347","356","590","680","789"],
    "5": ["140","159","168","230","249","258","267","348","357","456","690","780"],
    "6": ["123","150","169","178","240","259","268","349","358","457","367","790"],
    "7": ["124","160","179","250","269","278","340","359","368","458","467","890"],
    "8": ["125","134","170","189","260","279","350","369","378","459","567","468"],
    "9": ["126","135","180","234","270","289","360","379","450","469","478","568"],
    "0": ["127","136","145","190","235","280","370","479","460","569","389","578"],
}

DOUBLE_PATTI_GROUPS = {
    "1": ["100","119","155","227","335","344","399","588","669"],
    "2": ["200","110","228","255","336","499","660","688","778"],
    "3": ["300","166","229","337","355","445","599","779","788"],
    "4": ["400","112","220","266","338","446","455","699","770"],
    "5": ["500","113","122","177","339","366","447","799","889"],
    "6": ["600","114","277","330","448","466","556","880","899"],
    "7": ["700","115","133","188","223","377","449","557","566"],
    "8": ["800","116","224","233","288","440","477","558","990"],
    "9": ["900","117","144","199","225","388","559","577","667"],
    "0": ["550","668","244","299","226","488","677","118","334"],
}

TRIPPLE_PATTI_GROUPS = {
    "1": ["777"], "2": ["444"], "3": ["111"], "4": ["888"], "5": ["555"],
    "6": ["222"], "7": ["999"], "8": ["666"], "9": ["333"], "0": ["000"],
}

# --- AUTH VIEWS ---

def _get_safe_next_url(request, fallback="user_home"):
    candidate = request.POST.get("next") or request.GET.get("next")
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback if str(fallback).startswith("/") else reverse(fallback)


def _verify_recaptcha_response(request, recaptcha_response):
    if not recaptcha_response:
        return False

    secret_key = getattr(settings, "RECAPTCHA_SECRET_KEY", "")
    if not secret_key:
        logger.warning("reCAPTCHA verification skipped because RECAPTCHA_SECRET_KEY is not configured.")
        return False

    try:
        verify_response = requests.post(
            "https://www.google.com/recaptcha/api/siteverify",
            data={
                "secret": secret_key,
                "response": recaptcha_response,
                "remoteip": request.META.get("REMOTE_ADDR", ""),
            },
            timeout=10,
        )
        verify_response.raise_for_status()
        payload = verify_response.json()
        return bool(payload.get("success"))
    except requests.RequestException:
        logger.exception("reCAPTCHA verification request failed.")
        return False


def _parse_positive_minutes(value, label):
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{label} duration must be a whole number of minutes.")
    if minutes <= 0:
        raise ValidationError(f"{label} duration must be greater than zero.")
    return minutes


def _parse_datetime_local(value):
    if not value:
        return None

    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return timezone.localtime(dt)


def _client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip() or None


def _get_device_id(request):
    header_value = (request.headers.get("X-Device-ID") or "").strip()
    cookie_value = (request.COOKIES.get(DEVICE_ID_COOKIE_NAME) or "").strip()
    posted_value = (request.POST.get("device_id") or "").strip()
    device_id = header_value or cookie_value or posted_value
    if device_id:
        return device_id[:128]

    user_agent = request.META.get("HTTP_USER_AGENT", "")
    fallback = f"{_client_ip(request) or 'unknown'}::{user_agent[:160]}"
    return hashlib.sha256(fallback.encode("utf-8")).hexdigest()


def _set_device_cookie(response, device_id):
    response.set_cookie(
        DEVICE_ID_COOKIE_NAME,
        device_id,
        max_age=60 * 60 * 24 * 365,
        secure=not settings.DEBUG,
        httponly=False,
        samesite="Lax",
    )
    return response


def _bind_user_device_session(request, user):
    device_id = _get_device_id(request)
    current_session_key = request.session.session_key
    if not current_session_key:
        request.session.save()
        current_session_key = request.session.session_key

    with db_transaction.atomic():
        existing = (
            UserDeviceSession.objects.select_for_update()
            .filter(user=user, device_id=device_id, is_active=True)
            .exclude(session_key=current_session_key)
            .first()
        )
        if existing:
            from django.contrib.sessions.models import Session

            Session.objects.filter(session_key=existing.session_key).delete()
            existing.is_active = False
            existing.save(update_fields=["is_active", "last_seen_at"])

        UserDeviceSession.objects.update_or_create(
            session_key=current_session_key,
            defaults={
                "user": user,
                "device_id": device_id,
                "ip_address": _client_ip(request),
                "user_agent": request.META.get("HTTP_USER_AGENT", "")[:1000],
                "is_active": True,
            },
        )

    return device_id


def _market_timer_payload(market):
    now = timezone.localtime()

    def session_payload(start_time, end_time, duration_minutes, declared):
        remaining_seconds = None
        if end_time and not declared:
            remaining_seconds = max(0, int((end_time - now).total_seconds()))

        return {
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "duration_minutes": duration_minutes,
            "remaining_seconds": remaining_seconds,
            "declared": declared,
        }

    return {
        "id": market.id,
        "market_name": market.name,
        "collection_date": market.collection_date.isoformat() if market.collection_date else None,
        "open": session_payload(
            market.open_start_time,
            market.open_end_time,
            market.open_duration_minutes,
            bool(market.open_single),
        ),
        "close": session_payload(
            market.close_start_time,
            market.close_end_time,
            market.close_duration_minutes,
            bool(market.close_single),
        ),
        "timezone": settings.TIME_ZONE,
    }


def landing(request):
    safe_next = _get_safe_next_url(request)

    if request.session.get("captcha_verified"):
        if request.user.is_authenticated:
            if request.user.is_superuser:
                return redirect("admin_summary")
            return redirect(safe_next)
        return redirect(safe_next)

    if request.method == "POST":
        recaptcha_response = (request.POST.get("g-recaptcha-response") or "").strip()
        if _verify_recaptcha_response(request, recaptcha_response):
            request.session["captcha_verified"] = True
            request.session["captcha_verified_at"] = timezone.now().isoformat()
            return redirect(_get_safe_next_url(request))

        messages.error(request, "Please complete the security verification before entering the website.")

    return render(
        request,
        "landing.html",
        {
            "page_title": "Security Check",
            "recaptcha_site_key": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
            "next": safe_next,
        },
    )


@ratelimit(key='ip', rate='10/m', method='POST', block=False)
@ratelimit(key='post:username', rate='6/d', method='POST', block=False)
def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser:
            return redirect('admin_summary')
        return redirect('user_home')

    context = {}

    # Show a friendly message when the user was auto-logged out due to inactivity
    if request.GET.get('reason') == 'idle_timeout':
        messages.warning(request, "You were signed out automatically after 30 minutes of inactivity.")

    if request.method == 'POST':

        # 1. Detect if this is an AJAX JSON request or a standard Form POST
        is_ajax = request.content_type == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        user_n = request.POST.get('username')
        psw = request.POST.get('password')

        # Allow admins/staff to try unlimited times (no rate-limit blocks).
        # Keep rate limits for non-admin users and scanners.
        is_admin_username = False
        if user_n:
            is_admin_username = User.objects.filter(username__iexact=user_n, is_staff=True).exists()

        if getattr(request, "limited", False) and not is_admin_username:
            return ratelimit_exceeded(request)

        device_id = _get_device_id(request)
        user = authenticate(request, username=user_n, password=psw)
        
        if user is not None:
            # Enforce email verification for non-admin users
            if not user.is_superuser and not user.is_staff:
                try:
                    prof = user.profile
                    if prof.email and not prof.is_email_verified:
                        request.session["pending_email_verification_user_id"] = user.id
                        messages.error(request, "Please verify your email OTP before logging in.")
                        return redirect("verify_email_otp")
                except Profile.DoesNotExist:
                    pass

            login(request, user)
            
            _bind_user_device_session(request, user)

            try:
                profile = user.profile
                profile.session_key = request.session.session_key
                profile.save(update_fields=["session_key"])
            except Profile.DoesNotExist:
                pass

            messages.success(request, f"Welcome back, {user.username}!")
            
            if is_ajax:
                response = JsonResponse({'status': 'success'})
                return _set_device_cookie(response, device_id)
            
            if user.is_superuser:
                next_url = request.GET.get('next') or 'admin_summary'
            else:
                next_url = request.GET.get('next') or 'user_home'
            response = redirect(next_url)
            return _set_device_cookie(response, device_id)
        else:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Invalid username or password.'})
            
            messages.error(request, "Invalid username or password.")
            return render(request, 'auth/login.html', context)

    return render(request, 'auth/login.html', context)


def logout_view(request):
    if request.user.is_authenticated and request.session.session_key:
        UserDeviceSession.objects.filter(session_key=request.session.session_key).update(is_active=False)
    logout(request)
    messages.success(request, "LOGOUT SUCCESSFUL! You have been safely logged out.")
    return redirect('login')


@login_required
def session_idle_logout_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)

    if request.session.session_key:
        UserDeviceSession.objects.filter(session_key=request.session.session_key).update(is_active=False)
    logout(request)
    return JsonResponse({"status": "success"})


def _normalize_indian_mobile(raw):
    """Return (10-digit string, None) or (None, error_message)."""
    if not raw or not str(raw).strip():
        return None, "Mobile number is required."
    digits = re.sub(r"\D", "", str(raw).strip())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) != 10:
        return None, "Enter a valid 10-digit Indian mobile number."
    if digits[0] not in "6789":
        return None, "Mobile must be a valid Indian number (starts with 6–9)."
    return digits, None


def _is_disposable_email(email):
    """Check if the email domain is in the disposable email blocklist."""
    try:
        domain = email.split('@')[-1].lower()
        # Use a reliable list. Downloading every time is slow, but following user's logic.
        # In a real app, we'd cache this or use a library.
        url = 'https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/master/disposable_email_blocklist.conf'
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            disposable_domains = response.text.splitlines()
            return domain in [d.strip().lower() for d in disposable_domains if d.strip()]
    except Exception:
        # If the check fails (e.g. network error), allow the email to proceed but log it.
        pass
    return False


def _normalize_email(raw):
    raw = (raw or "").strip()
    if not raw:
        return None, "Email is required."
    if "@" not in raw or "." not in raw.split("@")[-1]:
        return None, "Enter a valid email address."
    return raw.lower(), None


def _generate_otp_6():
    return f"{secrets.randbelow(1_000_000):06d}"


def _send_email_otp(profile: Profile = None, email: str = None):
    """
    Sends OTP via Gmail SMTP server.
    Can be called with a Profile (for existing users) or an email (for pending registrations).
    """
    from django.core.mail import send_mail
    from django.conf import settings

    if not profile and not email:
        raise ValueError("Either profile or email must be provided to send OTP.")

    target_email = email or profile.email or profile.user.email
    ttl = int(getattr(settings, "EMAIL_OTP_TTL_SECONDS", 300))
    otp = _generate_otp_6()
    now = timezone.now()
    expires_at = now + timedelta(seconds=ttl)

    if profile:
        EmailOTP.objects.update_or_create(
            profile=profile,
            defaults={
                "otp_hash": make_password(otp),
                "expires_at": expires_at,
                "attempts": 0,
                "last_sent_at": now,
            },
        )
    else:
        # For pending registration, store by email
        EmailOTP.objects.update_or_create(
            email=target_email,
            defaults={
                "otp_hash": make_password(otp),
                "expires_at": expires_at,
                "attempts": 0,
                "last_sent_at": now,
            },
        )

    try:
        # Professional HTML template for Gmail
        html_message = f"""
        <div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 10px;">
            <div style="text-align: center; margin-bottom: 20px;">
                <h2 style="color: #2c3e50;">Email Verification Code</h2>
            </div>
            <div style="background-color: #f8f9fa; padding: 30px; border-radius: 8px; text-align: center;">
                <p style="font-size: 16px; color: #555;">To authenticate your account, please use the following One-Time Password (OTP):</p>
                <div style="font-size: 32px; font-weight: bold; color: #007bff; letter-spacing: 5px; margin: 20px 0; padding: 15px; border: 2px dashed #007bff; display: inline-block; background: #fff;">
                    {otp}
                </div>
                <p style="font-size: 14px; color: #888;">This OTP is valid for 5 minutes (300 seconds).</p>
            </div>
            <div style="margin-top: 25px; font-size: 13px; color: #999; text-align: center; line-height: 1.6;">
                <p>If you did not request this code, please ignore this email.</p>
                <p style="margin-top: 10px; font-weight: bold; color: #666;">&copy; {timezone.now().year} Changelifewithnumbers Team</p>
            </div>
        </div>
        """
        
        send_mail(
            subject="Your Verification Code - Changelifewithnumbers",
            message=f"Your email verification code is: {otp}. It expires in {ttl} seconds.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[target_email],
            fail_silently=False,
            html_message=html_message
        )
        return ttl
    except Exception as e:
        print(f"Gmail SMTP Error: {str(e)}")
        # Surface a clean user-facing error.
        raise ValidationError(
            f"Unable to send verification email. Please try again in a moment."
        )

@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def register_view(request):
    if request.user.is_authenticated:
        return redirect('user_home')

    def _register_context(extra=None):
        context = {
            "recaptcha_site_key": getattr(settings, "RECAPTCHA_SITE_KEY", ""),
        }
        if extra:
            context.update(extra)
        return context

    if request.method == 'POST':

        # Honeypot — bots often fill hidden fields
        if request.POST.get("website", "").strip():
            messages.error(request, "Registration could not be completed.")
            return render(request, 'auth/register.html', _register_context())

        recaptcha_response = (request.POST.get("g-recaptcha-response") or "").strip()
        if not _verify_recaptcha_response(request, recaptcha_response):
            messages.error(request, "Please complete the reCAPTCHA verification before creating your account.")
            return render(request, 'auth/register.html', _register_context())

        name = (request.POST.get('name') or '').strip()
        user_n = (request.POST.get('username') or '').strip()
        email_raw = request.POST.get('email') or ''
        psw = request.POST.get('password') or ''
        psw2 = request.POST.get('password2') or ''
        mob = request.POST.get('mobile') or ''
        terms_agree = request.POST.get('terms_agree')

        if not terms_agree:
            messages.error(request, "You must accept the terms and conditions to create an account.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))
        
        if not name or not user_n:
            messages.error(request, "Full name and username are required.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        if psw != psw2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        email_norm, email_err = _normalize_email(email_raw)
        if email_err:
            messages.error(request, email_err)
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        if _is_disposable_email(email_norm):
            messages.error(request, "Disposable email addresses are not allowed. Please use a permanent email provider (e.g. Gmail, Yahoo).")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        mobile_digits, mobile_err = _normalize_indian_mobile(mob)
        if mobile_err:
            messages.error(request, mobile_err)
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        if User.objects.filter(username__iexact=user_n).exists():
            messages.error(request, "Username already taken.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        if Profile.objects.filter(mobile=mobile_digits).exists():
            messages.error(request, "This mobile number is already registered.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        if Profile.objects.filter(email=email_norm).exists():
            messages.error(request, "This email is already registered.")
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        candidate = User(username=user_n, first_name=name)
        try:
            validate_password(psw, user=candidate)
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, 'auth/register.html', _register_context({
                'name': name, 'username': user_n, 'email': email_raw, 'mobile': mob
            }))

        # Store data in session instead of creating user
        request.session['pending_registration_data'] = {
            'username': user_n,
            'password': psw,
            'name': name,
            'email': email_norm,
            'mobile': mobile_digits,
        }
        
        try:
            _send_email_otp(email=email_norm)
            messages.success(request, "Please verify the OTP sent to your email to complete registration.")
            return redirect('verify_email_otp')
        except ValidationError as e:
            messages.error(request, str(e))
            return render(request, 'auth/register.html', _register_context())

    return render(request, 'auth/register.html', _register_context())


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def verify_email_otp_view(request):
    user_id = request.session.get("pending_email_verification_user_id")
    reg_data = request.session.get("pending_registration_data")
    
    if not user_id and not reg_data:
        messages.error(request, "No pending email verification found. Please register again.")
        return redirect("register")

    # Determine email for verification
    email = None
    profile = None
    if user_id:
        user = get_object_or_404(User, id=user_id)
        try:
            profile = user.profile
            email = profile.email
        except Profile.DoesNotExist:
            messages.error(request, "Profile not found.")
            return redirect("register")
    elif reg_data:
        email = reg_data.get('email')

    if not email:
        messages.error(request, "Email not found for verification.")
        return redirect("register")

    if profile and profile.is_email_verified:
        request.session.pop("pending_email_verification_user_id", None)
        messages.success(request, "Email already verified. You can log in now.")
        return redirect("login")

    ttl_seconds = int(getattr(settings, "EMAIL_OTP_TTL_SECONDS", 300))

    if request.method == "POST":
        otp = (request.POST.get("otp") or "").strip()
        if not otp or not otp.isdigit() or len(otp) != 6:
            messages.error(request, "Please enter a valid 6-digit OTP.")
            return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})

        try:
            if profile:
                rec = profile.email_otp
            else:
                rec = EmailOTP.objects.get(email=email, profile__isnull=True)
        except EmailOTP.DoesNotExist:
            messages.error(request, "OTP not found. Please resend OTP.")
            return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})

        if timezone.now() > rec.expires_at:
            messages.error(request, "OTP expired. Please resend OTP.")
            return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})

        max_attempts = int(getattr(settings, "EMAIL_OTP_MAX_ATTEMPTS", 5))
        if rec.attempts >= max_attempts:
            messages.error(request, "Maximum OTP attempts exceeded. Please resend OTP.")
            return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})

        if not check_password(otp, rec.otp_hash):
            rec.attempts = rec.attempts + 1
            rec.save(update_fields=["attempts"])
            remaining = max(0, max_attempts - rec.attempts)
            if remaining <= 0:
                messages.error(request, "Maximum OTP attempts exceeded. Please resend OTP.")
                return redirect("otp_result")
            messages.error(request, f"Invalid OTP. Attempts remaining: {remaining}.")
            return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})

        # Verification successful
        if reg_data:
            # Create the user now
            try:
                with db_transaction.atomic():
                    user = User.objects.create_user(
                        username=reg_data['username'],
                        password=reg_data['password'],
                        first_name=reg_data['name'],
                        email=reg_data['email']
                    )
                    profile = user.profile
                    profile.mobile = reg_data['mobile']
                    profile.email = reg_data['email']
                    profile.is_email_verified = True
                    profile.email_verified_at = timezone.now()
                    profile.save()

                    # Notify admin on Telegram
                    send_telegram_message(
                        f"🎉 <b>New User Registered</b>\n"
                        f"👤 Username: <b>{user.username}</b>\n"
                        f"📛 Name: {reg_data['name']}\n"
                        f"📧 Email: {reg_data['email']}\n"
                        f"📱 Mobile: {reg_data['mobile']}\n"
                        f"⏰ Time: {timezone.localtime().strftime('%d %b %Y, %I:%M %p')}"
                    )

                    # Send welcome message
                    admin_user = User.objects.filter(is_superuser=True).first()
                    if admin_user:
                        Message.objects.create(
                            sender=admin_user,
                            receiver=user,
                            content="Welcome to ChangeLifeWithNumbers! Play smart, win big."
                        )
                    
                    # Cleanup
                    EmailOTP.objects.filter(email=email).delete()
                    request.session.pop("pending_registration_data", None)
            except Exception as e:
                messages.error(request, f"Error creating account: {str(e)}")
                return redirect("register")
        else:
            # Legacy flow for existing users
            profile.is_email_verified = True
            profile.email_verified_at = timezone.now()
            profile.save(update_fields=["is_email_verified", "email_verified_at"])
            EmailOTP.objects.filter(profile=profile).delete()
            request.session.pop("pending_email_verification_user_id", None)

        # Set success flag in session for result page
        request.session["otp_verified_success"] = True
        return redirect("otp_result")

    return render(request, "auth/verify_email_otp.html", {"email": email, "ttl_seconds": ttl_seconds})


def otp_result_view(request):
    """Page to show success or failure after OTP verification."""
    success = request.session.pop("otp_verified_success", False)
    
    if success:
        return render(request, "auth/otp_result.html", {"status": "success"})
    
    # Check for error messages
    storage = messages.get_messages(request)
    msg_list = list(storage)
    message = msg_list[-1].message if msg_list else "Verification failed or session expired."
    
    return render(request, "auth/otp_result.html", {"status": "failure", "message": message})


@ratelimit(key="ip", rate="10/m", method="POST", block=True)
def resend_email_otp_view(request):
    if request.method != "POST":
        return redirect("verify_email_otp")

    user_id = request.session.get("pending_email_verification_user_id")
    reg_data = request.session.get("pending_registration_data")

    if not user_id and not reg_data:
        messages.error(request, "No pending email verification found.")
        return redirect("register")

    email = None
    profile = None
    if user_id:
        user = get_object_or_404(User, id=user_id)
        profile = getattr(user, "profile", None)
        if not profile or not profile.email:
            messages.error(request, "Email not found for verification.")
            return redirect("register")
        email = profile.email
    elif reg_data:
        email = reg_data.get('email')

    if not email:
        messages.error(request, "Email not found.")
        return redirect("register")

    if profile and profile.is_email_verified:
        request.session.pop("pending_email_verification_user_id", None)
        messages.success(request, "Email already verified.")
        return redirect("login")

    cooldown = int(getattr(settings, "EMAIL_OTP_RESEND_COOLDOWN_SECONDS", 60))
    now = timezone.now()
    
    try:
        if profile:
            rec = profile.email_otp
        else:
            rec = EmailOTP.objects.get(email=email, profile__isnull=True)
            
        if rec.last_sent_at and (now - rec.last_sent_at).total_seconds() < cooldown:
            wait = int(cooldown - (now - rec.last_sent_at).total_seconds())
            messages.error(request, f"Please wait {wait} seconds before requesting another OTP.")
            return redirect("verify_email_otp")
    except EmailOTP.DoesNotExist:
        pass

    try:
        if profile:
            _send_email_otp(profile=profile)
        else:
            _send_email_otp(email=email)
        messages.success(request, "A new OTP has been sent to your email.")
    except ValidationError as e:
        messages.error(request, str(e))

    return redirect("verify_email_otp")


# --- BASIC PAGES ---

def market_timing_api(request):
    """Returns persisted market countdown data for client-side timers."""
    markets = Market.objects.all()
    data = [_market_timer_payload(m) for m in markets]
    return JsonResponse(data, safe=False)


def error_404(request, exception):
    return render(request, 'errors/error.html', status=404)

def error_500(request):
    return render(request, 'errors/error.html', status=500)

def error_403(request, exception):
    return render(request, 'errors/403.html', status=403)

def error_400(request, exception):
    return render(request, 'errors/error.html', status=400)

def ratelimit_exceeded(request, exception=None):
    is_ajax = (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or request.content_type == "application/json"
    )
    if is_ajax:
        resp = JsonResponse(
            {"status": "error", "message": "Too many requests. Please wait and try again."},
            status=429,
        )
        resp["Retry-After"] = "60"
        return resp
    resp = render(request, "errors/429.html", status=429)
    resp["Retry-After"] = "60"
    return resp


def csrf_failure(request, reason=""):
    # Keep response generic (avoid leaking details), but helpful for users.
    context = {"reason": reason} if settings.DEBUG else {}
    return render(request, "errors/csrf_403.html", context, status=403)



def display(request):
    return render(request, 'user/display_page.html', {'markets': Market.objects.all()})


@user_passes_test(lambda u: u.is_superuser)
def create_market_timer_api(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)

    try:
        name = (request.POST.get("name") or "").strip()
        if not name:
            raise ValidationError("Market name is required.")

        open_duration = _parse_positive_minutes(request.POST.get("open_duration_minutes"), "Open")
        close_duration = _parse_positive_minutes(request.POST.get("close_duration_minutes"), "Close")
        collection_date = _parse_datetime_local(request.POST.get("collection_date")) or timezone.localtime()
        open_start_time = _parse_datetime_local(request.POST.get("open_start_time")) or timezone.localtime()
        close_start_time = _parse_datetime_local(request.POST.get("close_start_time")) or open_start_time

        with db_transaction.atomic():
            market = Market(name=name, collection_date=collection_date)
            market.configure_session_timer("OPEN", open_start_time, open_duration)
            market.configure_session_timer("CLOSE", close_start_time, close_duration)
            market.save()
    except ValidationError as exc:
        return JsonResponse({"status": "error", "message": exc.messages[0]}, status=400)
    except Exception:
        logger.exception("Market creation API failed.")
        return JsonResponse({"status": "error", "message": "Unable to create market timer."}, status=500)

    return JsonResponse({"status": "success", "market": _market_timer_payload(market)}, status=201)


@user_passes_test(lambda u: u.is_superuser)
def reset_market_timer_api(request, market_id):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)

    market = get_object_or_404(Market, id=market_id)
    now = timezone.localtime()

    try:
        with db_transaction.atomic():
            if request.POST.get("reset_open", "1") == "1":
                market.reset_session_timer("OPEN", now)
                market.open_patti = None
                market.open_single = None
                market.open_declared_at = None

            if request.POST.get("reset_close", "1") == "1":
                market.reset_session_timer("CLOSE", now)
                market.close_patti = None
                market.close_single = None
                market.close_declared_at = None

            market.save()
    except ValueError as exc:
        return JsonResponse({"status": "error", "message": str(exc)}, status=400)

    return JsonResponse({"status": "success", "market": _market_timer_payload(market)})


def user_home(request):
<<<<<<< HEAD
=======
    """
    Unified home page for both regular users and admins.
    - Regular users see the game home with markets, notice board, FAQ.
    - Admins see the same page but with an admin dashboard link in the nav.
    """
>>>>>>> 11445e8 (try1)
    return render(request, 'user/user_home.html', {
        'markets': Market.objects.all(),
        'page_title': 'Home',
    })


<<<<<<< HEAD
=======
@user_passes_test(lambda u: u.is_superuser)
def admin_home(request):
    # Kept for URL backward-compatibility — redirects to admin dashboard
    return redirect('admin_summary')


>>>>>>> 11445e8 (try1)
def error(request):
    return render(request, 'errors/error.html')


# --- UNIFIED BET PLACEMENT ENGINE ---

@login_required
@db_transaction.atomic
def place_bet(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)

    # 1. Detect if this is an AJAX JSON request or a standard Form POST
    is_ajax = request.content_type == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    
    if is_ajax:
        try:
            data = json.loads(request.body)
            market_id = data.get('market_id') or data.get('market')
            game_type = data.get('game_type')
            session = data.get('session')
            bets_data = data.get('bets')
            
            # Handle if 'bets' is a JSON string instead of an object
            if isinstance(bets_data, str):
                bets_data = json.loads(bets_data)
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid JSON data."})
    else:
        market_id = request.POST.get('market_id') or request.POST.get('market')
        game_type = request.POST.get('game_type')
        session = request.POST.get('session')
        bets_json = request.POST.get('bets') or request.POST.get('bets_json')
        try:
            bets_data = json.loads(bets_json) if bets_json else None
        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid bets data format."})

    try:
        if not market_id:
            return JsonResponse({"status": "error", "message": "Market ID is required."})
            
        market = Market.objects.get(id=market_id)

        if not bets_data:
            return JsonResponse({"status": "error", "message": "No bets provided."})

        if not market.is_betting_allowed(session):
            return JsonResponse({
                "status": "error",
                "message": "Betting is locked. Market closed or within 10-minute lockout."
            })

        total_amount = sum(int(amt) for amt in bets_data.values())

        wallet = request.user.wallet
        if wallet.balance < total_amount:
            return JsonResponse({"status": "error", "message": "Insufficient balance!"})

        wallet.balance -= total_amount
        wallet.save()

        Transaction.objects.create(
            wallet=wallet,
            amount=total_amount,
            txn_type='BET',
            description=f"{game_type} - {market.name}"
        )

        # Notification (Task 14)
        create_notification(
            request.user, 
            "Bet Placed Successfully", 
            f"You placed bets worth ₹{total_amount} on {market.name} ({game_type})."
        )

        try:
            prof = request.user.profile
            uid_display = prof.user_code if prof.user_code else str(request.user.id)
        except Profile.DoesNotExist:
            uid_display = str(request.user.id)
            
        for number, amount in bets_data.items():
            if int(amount) > 0:
                Bet.objects.create(
                    user=request.user,
                    user_id_str=uid_display,
                    game_type=game_type,
                    market=market,
                    session=session,
                    number=number,
                    amount=int(amount),
                    status='PENDING'
                )

        # Task 4: Stay on the same page instead of redirecting to history
        return JsonResponse({"status": "success", "message": "Bets placed successfully!"})

    except Market.DoesNotExist:
        return JsonResponse({"status": "error", "message": "Market not found."})
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({"status": "error", "message": f"Invalid data: {str(e)}"})
    except Exception as e:
        return JsonResponse({"status": "error", "message": str(e)})


# --- GAME VIEWS ---

@login_required
def single(request):
    if request.user.is_authenticated and request.user.is_superuser:
        return redirect('admin_summary')
    return render(request, "user/single.html", {
        "markets": Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        "game_title": "SINGLE",
        "game_type": "SINGLE",
    })


@login_required
def jodi(request):
    if request.user.is_superuser:
        return redirect('admin_summary')
    return render(request, 'user/jodi.html', {
        'markets': Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        'game_title': 'JODI',
        "game_type": "JODI",
    })


@login_required
def single_pathi(request):
    if request.user.is_superuser:
        return redirect('admin_summary')
    return render(request, "user/single_pathi.html", {
        "markets": Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        "game_title": "SINGLE PATTI",
        "game_type": "SINGLE_PATTI",
        "patti_groups": SINGLE_PATTI_GROUPS
    })


@login_required
def double_pathi(request):
    if request.user.is_superuser:
        return redirect('admin_summary')
    return render(request, 'user/single_pathi.html', {
        'markets': Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        'game_title': 'DOUBLE PATTI',
        'game_type': 'DOUBLE_PATTI',
        'patti_groups': DOUBLE_PATTI_GROUPS
    })


@login_required
def tripple_pathi(request):
    if request.user.is_superuser:
        return redirect('admin_summary')
    return render(request, 'user/single_pathi.html', {
        'markets': Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        'game_title': 'TRIPPLE PATTI',
        'game_type': 'TRIPLE_PATTI',
        'patti_groups': TRIPPLE_PATTI_GROUPS
    })


# --- WALLET & HISTORY ---

@login_required
def wallet_balance_api(request):
    return JsonResponse({
        "balance": float(request.user.wallet.balance),
        "username": request.user.username
    })


@login_required
def wallet_history_api(request):
    txns = request.user.wallet.transactions.order_by('-created_at')[:10]
    data = [
        {
            "amount": float(t.amount),
            "type": t.txn_type,
            "description": t.description,
            "date": t.created_at.strftime("%d %b, %H:%M")
        }
        for t in txns
    ]
    return JsonResponse({"history": data})


@login_required
def bet_history(request):
    date_filter = request.GET.get('date')
    market_filter = request.GET.get('market')
    session_filter = request.GET.get('session')

    bets = Bet.objects.filter(user=request.user).select_related('market').order_by('-created_at')

    if date_filter:
        # Use created_at__date for filtering based on string input from date picker
        # Also ensure we handle both 'date' field and 'created_at' field if needed,
        # but created_at__date is more reliable for DateTimeField.
        bets = bets.filter(created_at__date=date_filter)
    
    if market_filter and market_filter != '':
        bets = bets.filter(market_id=market_filter)
        
    if session_filter and session_filter != '':
        bets = bets.filter(session=session_filter)

    # Calculate totals AFTER filtering
    total_betted = bets.aggregate(Sum('amount'))['amount__sum'] or 0
    total_won = bets.aggregate(Sum('win_amount'))['win_amount__sum'] or 0

    markets = Market.objects.all()
    
    return render(request, 'user/bet_history.html', {
        'user_bets': bets,
        'markets': markets,
        'total_betted': total_betted,
        'total_won': total_won,
        'selected_date': date_filter,
        'selected_market': market_filter,
        'selected_session': session_filter,
    })


# --- ADMIN VIEWS ---

@user_passes_test(lambda u: u.is_superuser)
def admin_bet_history(request):
    """Admin view for all user bet history with specific columns."""
    date_filter = request.GET.get('date')
    market_filter = request.GET.get('market')
    user_filter = request.GET.get('user')
    session_filter = request.GET.get('session')

    bets = Bet.objects.select_related('user', 'user__profile', 'market').all().order_by('-created_at')

    if date_filter and date_filter != '':
        bets = bets.filter(created_at__date=date_filter)
    if market_filter and market_filter != '':
        bets = bets.filter(market_id=market_filter)
    if user_filter and user_filter != '':
        bets = bets.filter(user_id=user_filter)
    if session_filter and session_filter != '':
        bets = bets.filter(session=session_filter)

    markets = Market.objects.all()
    all_users = User.objects.exclude(is_superuser=True).select_related('profile')

    return render(request, 'admin/admin_bet_history.html', {
        'bets': bets,
        'markets': markets,
        'all_users': all_users,
        'selected_date': date_filter,
        'selected_market': market_filter,
        'selected_user': user_filter,
        'selected_session': session_filter,
    })


@user_passes_test(lambda u: u.is_superuser)
def declare_result(request):
    """
    Task 11: Combined result declaration with sequential declaration support.
    Admin can declare Open result (Patti-Single) first, then Close (Single-Patti).
    Enforced Pattern: Open: 123-1, Close: 1-123
    """
    markets = Market.objects.all()
    if request.method == "POST":
        market_id = request.POST.get('market_id')
        open_res = request.POST.get('open_result', '').strip()
        close_res = request.POST.get('close_result', '').strip()
        
        if not market_id:
            messages.error(request, "Please select a market.")
            return redirect('declare_result')
            
        market = Market.objects.get(id=market_id)
        
        with db_transaction.atomic():
            # Handle Open Result (Patti-Single, e.g. 123-6)
            if open_res:
                try:
                    if '-' not in open_res:
                        raise ValueError("Missing dash")
                    op, os = open_res.split('-')
                    if len(op) != 3 or len(os) != 1:
                        raise ValueError("Invalid lengths")
                    
                    market.open_patti = op.strip()
                    market.open_single = os.strip()
                    market.open_declared_at = timezone.now()
                    # Calculate winners for Open session
                    calculate_winners(market, session_to_calculate='OPEN')
                except ValueError:
                    messages.error(request, "Invalid Open result format. Use Patti-Single (e.g. 123-1).")
                    return redirect('declare_result')

            # Handle Close Result (Single-Patti, e.g. 7-601)
            if close_res:
                try:
                    if '-' not in close_res:
                        raise ValueError("Missing dash")
                    cs, cp = close_res.split('-')
                    if len(cs) != 1 or len(cp) != 3:
                        raise ValueError("Invalid lengths")
                        
                    market.close_single = cs.strip()
                    market.close_patti = cp.strip()
                    market.close_declared_at = timezone.now()
                    # Calculate winners for Close session and Jodi
                    calculate_winners(market, session_to_calculate='CLOSE')
                except ValueError:
                    messages.error(request, "Invalid Close result format. Use Single-Patti (e.g. 1-123).")
                    return redirect('declare_result')

            market.save()

        messages.success(request, f"Results updated for {market.name} successfully!")
        return redirect('declare_result')
        
    return render(request, 'admin/admin_declare_result.html', {'markets': markets})


def calculate_winners(market, session_to_calculate=None):
    """
    Business logic to compare admin result with user bets.
    Handles re-calculation if result is changed (Task 12).
    """
    # Get all bets for this market
    bets = Bet.objects.filter(market=market)
    
    # Filter by session if specified
    if session_to_calculate:
        if session_to_calculate == 'CLOSE':
            # Close session also calculates Jodi
            bets = bets.filter(Q(session='CLOSE') | Q(game_type='JODI'))
        else:
            bets = bets.filter(session=session_to_calculate)
    
    for bet in bets:
        old_status = bet.status
        is_winner = False
        win_ratio = 0
        
        # 1. Open Patti check
        if bet.session == 'OPEN' and bet.game_type in ['SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']:
            if market.open_patti and bet.number == market.open_patti:
                is_winner = True
                if bet.game_type == 'SINGLE_PATTI': win_ratio = 140
                elif bet.game_type == 'DOUBLE_PATTI': win_ratio = 280
                elif bet.game_type == 'TRIPLE_PATTI': win_ratio = 300
        
        # 2. Open Single check
        elif bet.session == 'OPEN' and bet.game_type == 'SINGLE':
            if market.open_single and bet.number == market.open_single:
                is_winner = True
                win_ratio = 9
                
        # 3. Close Single check
        elif bet.session == 'CLOSE' and bet.game_type == 'SINGLE':
            if market.close_single and bet.number == market.close_single:
                is_winner = True
                win_ratio = 9
                
        # 4. Close Patti check
        elif bet.session == 'CLOSE' and bet.game_type in ['SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']:
            if market.close_patti and bet.number == market.close_patti:
                is_winner = True
                if bet.game_type == 'SINGLE_PATTI': win_ratio = 140
                elif bet.game_type == 'DOUBLE_PATTI': win_ratio = 280
                elif bet.game_type == 'TRIPLE_PATTI': win_ratio = 300
                
        # 5. Jodi check
        elif bet.game_type == 'JODI':
            if market.open_single and market.close_single:
                jodi_result = f"{market.open_single}{market.close_single}"
                if bet.number == jodi_result:
                    is_winner = True
                    win_ratio = 90
            else:
                continue # Can't decide yet
        
        new_status = 'WIN' if is_winner else 'LOSS'
        
        # Determine if result for this bet is actually declared yet
        is_declared = False
        if bet.session == 'OPEN' and market.open_single: is_declared = True
        elif bet.session == 'CLOSE' and market.close_single: is_declared = True
        elif bet.game_type == 'JODI' and market.open_single and market.close_single: is_declared = True
        
        if not is_declared:
            continue

        if old_status == 'WIN' and new_status == 'LOSS':
            # Was a winner, now a loser (Correction)
            if bet.is_credited:
                # Deduct from wallet if already credited
                with db_transaction.atomic():
                    wallet = bet.user.wallet
                    wallet.balance -= Decimal(str(bet.win_amount))
                    wallet.save()
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=Decimal(str(bet.win_amount)),
                        txn_type='WITHDRAWAL',
                        description=f"CORRECTION: {bet.game_type} - {market.name} result changed to LOSS"
                    )
            bet.status = 'LOSS'
            bet.win_amount = 0
            bet.is_credited = False
            bet.save()
            
        elif (old_status == 'LOSS' or old_status == 'PENDING') and new_status == 'WIN':
            # Was a loser or pending, now a winner
            bet.status = 'WIN'
            bet.win_amount = float(bet.amount) * win_ratio
            bet.is_credited = False # Will be picked up by middleware
            bet.save()
            
        elif old_status == 'PENDING' and new_status == 'LOSS':
            # Just mark as loss
            bet.status = 'LOSS'
            bet.win_amount = 0
            bet.save()
        
        # If it was WIN and stays WIN, but win_amount changed (unlikely in Matka but possible)
        elif old_status == 'WIN' and new_status == 'WIN':
            new_win_amount = float(bet.amount) * win_ratio
            if float(bet.win_amount) != new_win_amount:
                # Handle win amount change correction
                diff = Decimal(str(new_win_amount)) - Decimal(str(bet.win_amount))
                if bet.is_credited:
                    with db_transaction.atomic():
                        wallet = bet.user.wallet
                        wallet.balance += diff
                        wallet.save()
                        Transaction.objects.create(
                            wallet=wallet,
                            amount=abs(diff),
                            txn_type='WIN' if diff > 0 else 'WITHDRAWAL',
                            description=f"CORRECTION: {bet.game_type} - {market.name} amount adjusted"
                        )
                bet.win_amount = new_win_amount
                bet.save()


@login_required
def jodi_winners_view(request):
    """
    Task 15: Separate Jodi winners view with date and market filters.
    """
    market_id = request.GET.get('market', 'ALL')
    date_filter = request.GET.get('date', '')
    
    winners = Bet.objects.filter(game_type='JODI', status='WIN').select_related('user', 'user__profile', 'market').order_by('-created_at')
    
    if market_id != 'ALL':
        winners = winners.filter(market_id=market_id)
    if date_filter:
        winners = winners.filter(created_at__date=date_filter)
        
    markets = Market.objects.all()
    return render(request, 'admin/jodi_winners.html', {
        'winners': winners,
        'markets': markets,
        'selected_market_id': market_id,
        'selected_date': date_filter
    })


@user_passes_test(lambda u: u.is_superuser)
def winners_list(request):
    """Display the PASS (Winner) table with filters."""
    game_type = request.GET.get('game_type', 'ALL')
    market_id = request.GET.get('market', 'ALL')
    session = request.GET.get('session', 'ALL')
    date_filter = request.GET.get('date', '')
    
    winners = Bet.objects.filter(status='WIN').select_related('user', 'user__profile', 'market')
    
    if game_type != 'ALL':
        winners = winners.filter(game_type=game_type)
    if market_id != 'ALL':
        winners = winners.filter(market_id=market_id)
    if session != 'ALL':
        winners = winners.filter(session=session)
    if date_filter:
        winners = winners.filter(created_at__date=date_filter)
        
    # Order by winning amount descending
    winners = winners.order_by('-created_at')
    
    markets = Market.objects.all()
    
    # Get the latest result for display
    latest_result = None
    if market_id != 'ALL':
        latest_result = Market.objects.filter(id=market_id).first()
    else:
        latest_result = Market.objects.exclude(open_single__isnull=True).order_by('-id').first()

    return render(request, 'admin/admin_winners.html', {
        'winners': winners,
        'markets': markets,
        'latest_result': latest_result,
        'selected_game_type': game_type,
        'selected_market_id': market_id,
        'selected_session': session,
        'selected_date': date_filter
    })


@user_passes_test(lambda u: u.is_superuser)
def organize_data_view(request):
    """Admin view for organized market data filtering by market, session and date."""
    markets = Market.objects.all()
    selected_market_id = request.GET.get('market')
    selected_session = request.GET.get('session', 'OPEN')
    selected_date = request.GET.get('date', '') # Default to empty for 'All'
    
    game_data = {gt: [] for gt in ['SINGLE', 'JODI', 'SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']}
    
    if selected_market_id:
        market = Market.objects.get(id=selected_market_id)
        bets = Bet.objects.filter(market=market, session=selected_session, is_deleted=False)
        
        if selected_date:
            bets = bets.filter(created_at__date=selected_date)
        
        stats = bets.values('number', 'game_type').annotate(
            total_amount=Sum('amount'),
            bet_count=Count('id')
        ).order_by('-total_amount') # Sort by amount descending
        
        for s in stats:
            gt = s['game_type']
            if gt in game_data:
                game_data[gt].append({
                    'number': s['number'],
                    'amount': s['total_amount']
                })

    # Find max length to iterate in rows
    max_rows = max([len(v) for v in game_data.values()] + [0])
    
    # Prepare rows: each row is a list of 5 cells (one for each game type)
    table_rows = []
    for i in range(max_rows):
        row = {
            'SINGLE': game_data['SINGLE'][i] if i < len(game_data['SINGLE']) else None,
            'JODI': game_data['JODI'][i] if (selected_session == 'OPEN' and i < len(game_data['JODI'])) else None,
            'SINGLE_PATTI': game_data['SINGLE_PATTI'][i] if i < len(game_data['SINGLE_PATTI']) else None,
            'DOUBLE_PATTI': game_data['DOUBLE_PATTI'][i] if i < len(game_data['DOUBLE_PATTI']) else None,
            'TRIPLE_PATTI': game_data['TRIPLE_PATTI'][i] if i < len(game_data['TRIPLE_PATTI']) else None,
        }
        table_rows.append(row)

    return render(request, 'admin/organize_data.html', {
        'markets': markets,
        'selected_market_id': selected_market_id,
        'selected_session': selected_session,
        'selected_date': selected_date,
        'table_rows': table_rows,
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_report(request):
    """
    Task 6: Generate detailed reports by date, market, and user.
    """
    date_str = request.GET.get('date', timezone.now().date().isoformat())
    market_id = request.GET.get('market')
    user_id = request.GET.get('user')
    
    if date_str and date_str != '':
        bets = Bet.objects.filter(created_at__date=date_str).select_related('user', 'market', 'user__wallet')
    else:
        # Fallback to today if no date provided
        bets = Bet.objects.filter(created_at__date=timezone.now().date()).select_related('user', 'market', 'user__wallet')
    
    if market_id and market_id != '' and market_id != 'None':
        bets = bets.filter(market_id=market_id)
    if user_id and user_id != '' and user_id != 'None':
        bets = bets.filter(user_id=user_id)
        
    # Group by user directly using Django aggregation to avoid duplicates
    user_stats = bets.values('user_id').annotate(
        total_betted=Sum('amount'),
        total_won=Sum('win_amount')
    ).order_by('user_id')

    report_data = []
    for stat in user_stats:
        uid = stat['user_id']
        # Fetch the user object with profile and wallet
        try:
            user_obj = User.objects.select_related('profile', 'wallet').get(id=uid)
            prof = user_obj.profile
            user_code = prof.user_code
        except (User.DoesNotExist, Profile.DoesNotExist):
            continue # Should not happen with valid bets
            
        total_betted = stat['total_betted'] or 0
        total_won = stat['total_won'] or 0
        net_pl = total_won - total_betted

        report_data.append({
            'user': user_obj,
            'user_code': user_code,
            'total_betted': total_betted,
            'total_won': total_won,
            'net_pl': net_pl,
            'balance': user_obj.wallet.balance,
        })
        
    markets = Market.objects.all()
    all_users = User.objects.exclude(is_superuser=True).select_related('profile')
    
    return render(request, 'admin/admin_report.html', {
        'report_data': report_data,
        'markets': markets,
        'all_users': all_users,
        'selected_date': date_str,
        'selected_market': market_id,
        'selected_user': user_id,
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_market_alerts(request):
    """API for admin to get markets expiring in the next 10 minutes."""
    now = timezone.now()
    alert_window = timedelta(minutes=10)
    
    expiring_markets = []
    
    markets = Market.objects.all()
    for m in markets:
        # Check Open Session
        if m.open_end_time and not (m.open_single or m.open_patti):
            diff = m.open_end_time - now
            if timedelta(0) < diff <= alert_window:
                expiring_markets.append({
                    "name": m.name,
                    "session": "OPEN",
                    "time_left": int(diff.total_seconds() / 60)
                })
        
        # Check Close Session
        if m.close_end_time and not (m.close_single or m.close_patti):
            diff = m.close_end_time - now
            if timedelta(0) < diff <= alert_window:
                expiring_markets.append({
                    "name": m.name,
                    "session": "CLOSE",
                    "time_left": int(diff.total_seconds() / 60)
                })
                
    return JsonResponse({"alerts": expiring_markets})

@login_required
@user_passes_test(lambda u: u.is_superuser)
def export_user_data(request):
    import csv
    from django.http import HttpResponse
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="users_export_{timezone.now().strftime("%Y%m%d")}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Username', 'User Code', 'Mobile', 'Wallet Balance', 'Created At'])
    
    profiles = Profile.objects.select_related('user', 'user__wallet').all()
    for profile in profiles:
        balance = profile.user.wallet.balance if hasattr(profile.user, 'wallet') else 0
        writer.writerow([
            profile.user.username,
            profile.user_code,
            profile.mobile,
            balance,
            profile.created_at.strftime("%Y-%m-%d %H:%M")
        ])
    
    return response

@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_summary(request):
    """Admin dashboard overview with 30-day cleanup."""
    if request.method == 'POST' and request.POST.get('action') == 'cleanup_30days':
        # ... (cleanup logic remains same)
        cutoff_date = timezone.now() - timedelta(days=30)
        
        with db_transaction.atomic():
            # 1. Archive & Delete MarketHistory older than 30 days
            MarketHistory.objects.filter(archived_at__lt=cutoff_date).delete()
            
            # 2. Delete Admin Chat (Messages) older than 30 days
            Message.objects.filter(created_at__lt=cutoff_date).delete()
            
            # 3. Delete User Bets older than 30 days
            Bet.objects.filter(created_at__lt=cutoff_date).delete()
            
            # 4. Delete Payment Approval History (DepositRequest) older than 30 days
            DepositRequest.objects.filter(created_at__lt=cutoff_date).delete()
            
            # 5. Delete Withdrawal Requests older than 30 days
            WithdrawalRequest.objects.filter(created_at__lt=cutoff_date).delete()
            
            # 6. Delete Notifications older than 30 days
            Notification.objects.filter(created_at__lt=cutoff_date).delete()
            
            # Log this cleanup activity
            UserActivity.objects.create(
                user=request.user,
                activity_type='CLEANUP',
                description=f"Admin performed 30-day data cleanup for data before {cutoff_date.strftime('%Y-%m-%d %H:%M')}"
            )
            
        messages.success(request, f"Successfully cleaned up all data older than 30 days (before {cutoff_date.strftime('%d %b %Y')}).")
        return redirect('admin_summary')

    total_users = User.objects.exclude(is_superuser=True).count()
    
    # Financial Stats
    date_filter = request.GET.get('date')
    if date_filter:
        try:
            today = datetime.strptime(date_filter, '%Y-%m-%d').date()
        except ValueError:
            today = timezone.now().date()
    else:
        today = timezone.now().date()

    today_bets = Bet.objects.filter(created_at__date=today, is_deleted=False)
    today_collection = today_bets.aggregate(Sum('amount'))['amount__sum'] or 0
    today_payouts = today_bets.aggregate(Sum('win_amount'))['win_amount__sum'] or 0
    today_profit = today_collection - today_payouts
    
    pending_withdrawals = WithdrawalRequest.objects.filter(status='PENDING').count()
    pending_deposits = DepositRequest.objects.filter(status='PENDING').count()
    
    # Recent activities
    recent_activities = UserActivity.objects.all()[:10]
    
    # Market Summary for Selected Date
    market_summary = today_bets.values('market__name', 'game_type').annotate(
        total_amount=Sum('amount'),
        count=Count('id')
    ).order_by('-total_amount')
    
    # Recent Transactions (Last 10)
    recent_txns = Transaction.objects.select_related('wallet__user').order_by('-created_at')[:10]

    return render(request, "admin/admin_summary.html", {
        "page_title": "Admin Dashboard",
        "today": today,
        "total_users": total_users,
        "today_collection": today_collection,
        "today_payouts": today_payouts,
        "today_profit": today_profit,
        "pending_withdrawals": pending_withdrawals,
        "pending_deposits": pending_deposits,
        "market_summary": market_summary,
        "recent_txns": recent_txns,
        "recent_activities": recent_activities,
        "selected_date": date_filter or today.strftime('%Y-%m-%d')
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
def admin_dashboard_enhanced(request):
    """Enhanced admin dashboard with Tailwind CSS styling."""
    if request.method == 'POST' and request.POST.get('action') == 'cleanup_30days':
        cutoff_date = timezone.now() - timedelta(days=30)
        
        with db_transaction.atomic():
            MarketHistory.objects.filter(archived_at__lt=cutoff_date).delete()
            Message.objects.filter(created_at__lt=cutoff_date).delete()
            Bet.objects.filter(created_at__lt=cutoff_date).delete()
            DepositRequest.objects.filter(created_at__lt=cutoff_date).delete()
            WithdrawalRequest.objects.filter(created_at__lt=cutoff_date).delete()
            Notification.objects.filter(created_at__lt=cutoff_date).delete()
            
            UserActivity.objects.create(
                user=request.user,
                activity_type='CLEANUP',
                description=f"Admin performed 30-day data cleanup"
            )
            
        messages.success(request, "Successfully cleaned up all data older than 30 days.")
        return redirect('admin_dashboard_enhanced')

    total_users = User.objects.exclude(is_superuser=True).count()
    
    today = timezone.now().date()
    today_bets = Bet.objects.filter(created_at__date=today, is_deleted=False)
    today_collection = today_bets.aggregate(Sum('amount'))['amount__sum'] or 0
    today_payouts = today_bets.aggregate(Sum('win_amount'))['win_amount__sum'] or 0
    today_profit = today_collection - today_payouts
    
    pending_withdrawals = WithdrawalRequest.objects.filter(status='PENDING').count()
    pending_deposits = DepositRequest.objects.filter(status='PENDING').count()
    
    market_summary = today_bets.values('market__name', 'game_type').annotate(
        total_amount=Sum('amount'),
        count=Count('id')
    ).order_by('-total_amount')
    
    recent_txns = Transaction.objects.select_related('wallet__user').order_by('-created_at')[:10]
    markets = Market.objects.all()

    return render(request, "admin/dashboard_content.html", {
        "page_title": "Admin Dashboard",
        "total_users": total_users,
        "today_collection": today_collection,
        "today_payouts": today_payouts,
        "today_profit": today_profit,
        "pending_withdrawals": pending_withdrawals,
        "pending_deposits": pending_deposits,
        "market_summary": market_summary,
        "recent_txns": recent_txns,
        "markets": markets,
    })


@login_required
def delete_bet(request, bet_id):
    """User can delete their own bet with specific restrictions."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST allowed'})
        
    bet = get_object_or_404(Bet, id=bet_id, user=request.user)
    
    # 1. Check if already deleted
    if bet.is_deleted:
        return JsonResponse({'status': 'error', 'message': 'This bet is already deleted.'})
        
    # 2. Check if within 24 hours of placement
    if timezone.now() > bet.created_at + timedelta(hours=24):
        return JsonResponse({'status': 'error', 'message': 'Bets can only be deleted within 24 hours of placement.'})
        
    # 3. Check if market is still open and not in lockout (last 10 mins)
    market = bet.market
    if not market.is_betting_allowed(bet.session):
        return JsonResponse({'status': 'error', 'message': 'Betting is locked. You cannot delete bets in the last 10 minutes or after market close.'})
        
    # 4. Check if result is already declared
    if bet.session == 'OPEN':
        if market.open_single or market.open_patti:
            return JsonResponse({'status': 'error', 'message': 'Result already declared for this session. Cannot delete bet.'})
    else:
        if market.close_single or market.close_patti:
            return JsonResponse({'status': 'error', 'message': 'Result already declared for this session. Cannot delete bet.'})
            
    # 5. Check daily limit (3 bets per day)
    today_deleted_count = Bet.objects.filter(
        user=request.user, 
        is_deleted=True, 
        deleted_at__date=timezone.now().date()
    ).count()
    
    if today_deleted_count >= 3:
        return JsonResponse({'status': 'error', 'message': 'Daily deletion limit (3 bets) reached.'})
        
    # Perform deletion
    with db_transaction.atomic():
        bet.is_deleted = True
        bet.deleted_at = timezone.now()
        bet.status = 'REJECTED' # Mark as rejected to avoid win calculation
        bet.save()
        
        # Log activity for admin
        UserActivity.objects.create(
            user=request.user,
            activity_type='BET_DELETE',
            description=f"Deleted {bet.game_type} bet of ₹{bet.amount} on {market.name} ({bet.session})"
        )
        
    return JsonResponse({'status': 'success', 'message': 'Bet deleted successfully. Refund will be credited to your wallet in 10 minutes after verification.'})


@user_passes_test(lambda u: u.is_superuser)
def admin_user_activity(request):
    """Admin view to monitor all user activities including bet deletions."""
    activities = UserActivity.objects.select_related('user', 'user__profile').all().order_by('-created_at')
    
    # Process pending refunds for deleted bets (Task 4)
    # This logic checks for deleted bets that are older than 10 mins and not yet refunded.
    # We find transactions to see if a refund was already issued.
    ten_mins_ago = timezone.now() - timedelta(minutes=10)
    pending_refund_bets = Bet.objects.filter(
        is_deleted=True, 
        deleted_at__lte=ten_mins_ago,
        status='REJECTED' # REJECTED means deleted but not yet refunded in our logic
    )
    
    refund_count = 0
    for bet in pending_refund_bets:
        # Check if already refunded by looking for a transaction
        exists = Transaction.objects.filter(
            wallet__user=bet.user,
            txn_type='DEPOSIT',
            description__icontains=f"Refund for Deleted Bet #{bet.id}"
        ).exists()
        
        if not exists:
            with db_transaction.atomic():
                wallet = bet.user.wallet
                wallet.balance += Decimal(str(bet.amount))
                wallet.save()
                
                Transaction.objects.create(
                    wallet=wallet,
                    amount=Decimal(str(bet.amount)),
                    txn_type='DEPOSIT',
                    description=f"Refund for Deleted Bet #{bet.id} ({bet.game_type})"
                )
                
                # Update status so we don't process it again
                bet.status = 'LOSS' # Using LOSS as a final processed state for deleted bets
                bet.save()
                refund_count += 1
                
    if refund_count > 0:
        messages.info(request, f"Processed {refund_count} pending bet refunds automatically.")

    return render(request, 'admin/admin_user_activity.html', {
        'activities': activities,
        'page_title': 'User Activity Logs'
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_user_management(request):
    """Page 1: Message new users and see verification status."""
    profiles = Profile.objects.select_related('user').all().order_by('-created_at')
    # Mark all as seen when admin visits this page
    Profile.objects.filter(is_new=True).update(is_new=False)
    return render(request, 'admin/admin_user_management.html', {
        'profiles': profiles,
        'page_title': 'User Management'
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_chat_list(request):
    """Page 2: WhatsApp style chat list with search and date info."""
    search_query = request.GET.get('search', '').strip()
    
    # Task 1: Hide chat column (user) if no messages exist
    users_qs = User.objects.exclude(is_superuser=True).filter(
        Q(received_messages__sender=request.user) | Q(sent_messages__receiver=request.user)
    ).distinct()
    
    if search_query:
        users_qs = users_qs.filter(
            Q(username__icontains=search_query) | 
            Q(profile__user_code__icontains=search_query)
        )
        
    # Annotate with last message time and unread count
    users = users_qs.annotate(
        last_message_at=Max('received_messages__created_at'),
        unread_count=Count('sent_messages', filter=Q(sent_messages__receiver=request.user, sent_messages__is_read=False))
    ).order_by('-last_message_at')
    
    return render(request, 'admin/admin_chat_list.html', {
        'users': users,
        'search_query': search_query
    })


@login_required
def chat_view(request, user_id=None):
    """Unified chat view for User-Admin messaging with image support and auto-delete."""
    if request.user.is_superuser:
        if not user_id:
            return redirect('admin_chat_list')
        other_user = User.objects.get(id=user_id)
        # Mark messages as read when admin opens the chat
        Message.objects.filter(sender=other_user, receiver=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )
    else:
        # Normal user can only chat with admin
        other_user = User.objects.filter(is_superuser=True).first()
        if not other_user:
            return redirect('error')
        # Mark admin's messages as read when user opens the chat
        Message.objects.filter(sender=other_user, receiver=request.user, is_read=False).update(
            is_read=True,
            read_at=timezone.now()
        )

    # Perform background cleanup of auto-deleted messages (older than 30 mins)
    thirty_mins_ago = timezone.now() - timedelta(minutes=30)
    Message.objects.filter(
        auto_delete=True,
        is_read=True,
        read_at__lte=thirty_mins_ago
    ).delete()

    if request.method == 'POST':
        content = request.POST.get('content')
        image = request.FILES.get('image')
        auto_delete = request.POST.get('auto_delete') == 'on' if request.user.is_superuser else False
        
        if content or image:
            Message.objects.create(
                sender=request.user, 
                receiver=other_user, 
                content=content,
                image=image,
                auto_delete=auto_delete
            )

            # Notify admin on Telegram when a user sends a message
            if not request.user.is_superuser:
                msg_preview = (content[:100] + "…") if content and len(content) > 100 else (content or "📷 Image")
                send_telegram_message(
                    f"💬 <b>New Chat Message</b>\n"
                    f"👤 From: <b>{request.user.username}</b>\n"
                    f"📝 Message: {msg_preview}\n"
                    f"⏰ Time: {timezone.localtime().strftime('%d %b %Y, %I:%M %p')}\n"
                    f"🔗 Reply at: /admin-chat-user/{request.user.id}/"
                )

            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
            return redirect('chat') if not request.user.is_superuser else redirect('admin_chat_user', user_id=other_user.id)

    # Get messages between these two users
    messages_list = Message.objects.filter(
        (Q(sender=request.user) & Q(receiver=other_user)) |
        (Q(sender=other_user) & Q(receiver=request.user))
    ).order_by('created_at')

    # Group messages by date for WhatsApp style display
    from collections import OrderedDict
    grouped_messages = {}
    for msg in messages_list:
        date_str = msg.created_at.date().strftime('%Y-%m-%d')
        if date_str not in grouped_messages:
            grouped_messages[date_str] = []
        grouped_messages[date_str].append(msg)

    return render(request, 'user/chat.html', {
        'other_user': other_user,
        'grouped_messages': grouped_messages,
        'today_date': timezone.now().date().strftime('%Y-%m-%d'),
        'yesterday_date': (timezone.now() - timedelta(days=1)).date().strftime('%Y-%m-%d'),
        'page_title': f'Chat with {other_user.username}'
    })


@user_passes_test(lambda u: u.is_superuser)
def send_welcome_msg(request, user_id):
    """Ajax endpoint to send welcome message."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Only POST allowed'})
    user = User.objects.get(id=user_id)
    content = f"Hi {user.username}, welcome to ChangeLifeWithNumbers!"
    Message.objects.create(sender=request.user, receiver=user, content=content)
    return JsonResponse({'status': 'success'})


@login_required
@ratelimit(key='ip', rate='10/m', method='POST', block=True)
def payment_page(request):
    """Payment form with QR redirect and UTR submission."""
    if request.method == 'POST':
        # 1. Handle Amount Submission (Initial step)
        if 'amount' in request.POST and 'utr_number' not in request.POST:
            amount_raw = request.POST.get('amount')
            try:
                amount = Decimal(amount_raw)
            except:
                messages.error(request, "Invalid amount format.")
                return redirect('payment')

            if amount < 100:
                messages.error(request, "Minimum deposit amount is ₹100.")
                return redirect('payment')
            
            # Get UPI config
            config = PaymentSettings.objects.filter(is_active=True).last()
            upi_id = config.upi_id if config else '8217228766'
            payee_name = config.payee_name if config else 'SERVICE'
            
            # Generate UPI URL with natural note
            upi_url = f"upi://pay?pa={upi_id}&pn={payee_name}&am={amount}&cu=INR"
            
            return render(request, 'user/payment_qr.html', {
                'amount': amount,
                'upi_url': upi_url
            })

        # 2. Handle UTR submission (Final step from payment_qr.html)
        amount = Decimal(request.POST.get('amount', 0))
        utr_number = request.POST.get('utr_number', '').strip()
        
        if not utr_number or len(utr_number) < 10:
            return JsonResponse({'status': 'error', 'message': 'Please enter a valid 12-digit UTR.'})
            
        if amount < 100:
            return JsonResponse({'status': 'error', 'message': 'Minimum amount is ₹100.'})
            
        # Check if UTR already exists
        if DepositRequest.objects.filter(utr_number=utr_number).exists():
            return JsonResponse({'status': 'error', 'message': 'This UTR has already been submitted.'})
            
        DepositRequest.objects.create(
            user=request.user,
            amount=amount,
            utr_number=utr_number,
            status='PENDING'
        )

        # Notify admin on Telegram
        send_telegram_message(
            f"💰 <b>New Deposit Request</b>\n"
            f"👤 User: <b>{request.user.username}</b>\n"
            f"💵 Amount: <b>₹{amount}</b>\n"
            f"🔖 UTR: <code>{utr_number}</code>\n"
            f"⏰ Time: {timezone.localtime().strftime('%d %b %Y, %I:%M %p')}"
        )

        return JsonResponse({'status': 'success', 'message': 'UTR submitted successfully! Your wallet will be updated after verification.'})

    # Standard GET: Show initial amount entry form
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, 'user/payment.html', {
        'username': request.user.username,
        'mobile': profile.mobile or "Not set",
        'user_code': profile.user_code or "N/A"
    })


@user_passes_test(lambda u: u.is_superuser)
def admin_payment_management(request):
    """Admin view to manage UPI ID and approve deposits."""
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'update_upi':
            upi_id = request.POST.get('upi_id')
            payee_name = request.POST.get('payee_name', 'SERVICE')
            if upi_id:
                # Deactivate others and create new
                PaymentSettings.objects.all().update(is_active=False)
                PaymentSettings.objects.create(upi_id=upi_id, payee_name=payee_name, is_active=True)
                messages.success(request, f"Active UPI ID updated to {upi_id} ({payee_name})")
            return redirect('admin_payment_management')
            
        elif action == 'approve_deposit':
            req_id = request.POST.get('request_id')
            try:
                deposit = DepositRequest.objects.get(id=req_id, status='PENDING')
                with db_transaction.atomic():
                    deposit.status = 'APPROVED'
                    deposit.save()
                    
                    # Add balance to user wallet
                    wallet, _ = Wallet.objects.get_or_create(user=deposit.user)
                    wallet.balance += deposit.amount
                    wallet.save()
                    
                    # Create transaction log
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=deposit.amount,
                        txn_type='DEPOSIT',
                        description=f"Deposit via UTR: {deposit.utr_number}"
                    )
                    
                    # Create notification
                    create_notification(
                        deposit.user,
                        "Deposit Approved",
                        f"Your deposit of ₹{deposit.amount} has been approved and added to your wallet."
                    )
                messages.success(request, f"Deposit of ₹{deposit.amount} approved for {deposit.user.username}")
            except DepositRequest.DoesNotExist:
                messages.error(request, "Request not found or already processed.")
            return redirect('admin_payment_management')
            
        elif action == 'reject_deposit':
            req_id = request.POST.get('request_id')
            try:
                deposit = DepositRequest.objects.get(id=req_id, status='PENDING')
                deposit.status = 'REJECTED'
                deposit.save()
                messages.warning(request, f"Deposit rejected for {deposit.user.username}")
            except DepositRequest.DoesNotExist:
                messages.error(request, "Request not found or already processed.")
            return redirect('admin_payment_management')

        elif action == 'auto_approve':
            utr_number = request.POST.get('utr_number', '').strip()
            if not utr_number:
                messages.error(request, "Please enter a UTR number.")
                return redirect('admin_payment_management')
                
            try:
                # Find the pending request with this UTR
                deposit = DepositRequest.objects.get(utr_number=utr_number, status='PENDING')
                with db_transaction.atomic():
                    deposit.status = 'APPROVED'
                    deposit.save()
                    
                    wallet, _ = Wallet.objects.get_or_create(user=deposit.user)
                    wallet.balance += deposit.amount
                    wallet.save()
                    
                    Transaction.objects.create(
                        wallet=wallet,
                        amount=deposit.amount,
                        txn_type='DEPOSIT',
                        description=f"Auto-Approved Deposit UTR: {deposit.utr_number}"
                    )
                    
                    create_notification(
                        deposit.user,
                        "Deposit Auto-Approved",
                        f"Your deposit of ₹{deposit.amount} was auto-approved via UTR verification."
                    )
                messages.success(request, f"UTR {utr_number} auto-approved! ₹{deposit.amount} added to {deposit.user.username}'s wallet.")
            except DepositRequest.DoesNotExist:
                messages.error(request, f"No pending request found with UTR {utr_number}")
            return redirect('admin_payment_management')

    # Get active UPI
    active_config = PaymentSettings.objects.filter(is_active=True).last()
    
    # Filter pending deposits
    utr_search = request.GET.get('utr_search', '')
    pending_deposits = DepositRequest.objects.filter(status='PENDING').order_by('-created_at')
    if utr_search:
        pending_deposits = pending_deposits.filter(utr_number__icontains=utr_search)
        
    # Get approved history
    recent_approved = DepositRequest.objects.filter(status='APPROVED').order_by('-updated_at')[:20]

    return render(request, 'admin/admin_payment_management.html', {
        'active_upi': active_config.upi_id if active_config else '',
        'active_payee': active_config.payee_name if active_config else '',
        'pending_deposits': pending_deposits,
        'recent_approved': recent_approved,
        'utr_search': utr_search,
        'today': timezone.now()
    })


@user_passes_test(lambda u: u.is_superuser)
def reset_market(request, market_id):
    """
    Task: Reset a market, archive its results and timing into MarketHistory.
    """
    market = get_object_or_404(Market, id=market_id)
    
    # Archive current data
    MarketHistory.objects.create(
        market=market,
        collection_date=market.collection_date,
        open_patti=market.open_patti,
        open_single=market.open_single,
        close_patti=market.close_patti,
        close_single=market.close_single
    )
    
    now = timezone.localtime()

    # Reset market timers while preserving persisted durations if they exist.
    market.collection_date = now
    if market.open_duration_minutes:
        market.reset_session_timer("OPEN", now)
    else:
        market.open_start_time = None
        market.open_end_time = None
    if market.close_duration_minutes:
        market.reset_session_timer("CLOSE", now)
    else:
        market.close_start_time = None
        market.close_end_time = None
    market.open_patti = None
    market.open_single = None
    market.open_declared_at = None
    market.close_patti = None
    market.close_single = None
    market.close_declared_at = None
    market.save()
    
    messages.success(request, f"Market '{market.name}' has been reset and its persisted countdown restarted.")
    return redirect('manage_markets')


@user_passes_test(lambda u: u.is_superuser)
def market_history_view(request):
    """
    View for admin to see all archived market history.
    """
    history = MarketHistory.objects.select_related('market').all()
    return render(request, 'admin/admin_market_history.html', {'history': history})


@user_passes_test(lambda u: u.is_staff)
@user_passes_test(lambda u: u.is_superuser)
def manage_markets(request):
    """
    Task 16: Manage markets with date-time picker.
    """
    if request.method == "POST":
        name = request.POST.get('name')
        coll_date = request.POST.get('collection_date')
        ost = request.POST.get('open_start_time')
        open_duration = request.POST.get('open_duration_minutes')
        cst = request.POST.get('close_start_time')
        close_duration = request.POST.get('close_duration_minutes')

        try:
            collection_date = _parse_datetime_local(coll_date) or timezone.localtime()
            open_start_time = _parse_datetime_local(ost) or timezone.localtime()
            close_start_time = _parse_datetime_local(cst) or open_start_time
            open_duration_minutes = _parse_positive_minutes(open_duration, "Open")
            close_duration_minutes = _parse_positive_minutes(close_duration, "Close")

            market = Market(name=name, collection_date=collection_date)
            market.configure_session_timer("OPEN", open_start_time, open_duration_minutes)
            market.configure_session_timer("CLOSE", close_start_time, close_duration_minutes)
            market.save()
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
            return redirect('manage_markets')

        messages.success(request, f"Market '{name}' created successfully!")
        return redirect('manage_markets')
        
    return render(request, "admin/manage_markets.html", {"markets": Market.objects.all().order_by('name')})


@user_passes_test(lambda u: u.is_staff)
def market_bets(request):
    return render(request, "admin/market_bets.html", {"bets": Bet.objects.all()})

from .forms import MyContactForm

def contact_view(request):
    if request.method == 'POST':
        form = MyContactForm(request.POST)
        if form.is_valid():
            return render(request, 'success.html')
    else:
        form = MyContactForm()
    
    return render(request, 'contact.html', {'form': form})


def _get_telegram_bot_token():
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _get_telegram_admin_chat_id():
    return (os.getenv("TELEGRAM_ADMIN_CHAT_ID") or "").strip()


# ---------------------------------------------------------------------------
# send_telegram_message — fire-and-forget, thread-safe, PythonAnywhere-safe
# ---------------------------------------------------------------------------
# PythonAnywhere's WSGI workers are synchronous.  Running an async coroutine
# inside a sync view (or blocking on requests.post) would stall the worker.
# We push every outbound Telegram message onto a background daemon thread so
# the HTTP response is returned to the user immediately (< 5 ms overhead).
# ---------------------------------------------------------------------------

def send_telegram_message(text: str, chat_id: str = None, token: str = None) -> None:
    """
    Send a Telegram message in a background thread.

    Args:
        text:    Message body (HTML formatting supported).
        chat_id: Destination chat/user ID.  Defaults to TELEGRAM_ADMIN_CHAT_ID.
        token:   Bot token.  Defaults to TELEGRAM_BOT_TOKEN env var.

    The function returns immediately; the actual HTTP call happens in a daemon
    thread so it never blocks the Django request/response cycle.
    """
    _token   = token   or _get_telegram_bot_token()
    _chat_id = chat_id or _get_telegram_admin_chat_id()

    if not _token or not _chat_id:
        logger.warning(
            "[TelegramNotify] Skipped — TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_ADMIN_CHAT_ID not configured."
        )
        return

    def _send():
        url = f"https://api.telegram.org/bot{_token}/sendMessage"
        payload = {
            "chat_id":    _chat_id,
            "text":       text,
            "parse_mode": "HTML",
        }
        try:
            resp = requests.post(url, json=payload, timeout=8)
            if not resp.ok:
                logger.warning(
                    "[TelegramNotify] API returned %s: %s",
                    resp.status_code, resp.text[:200],
                )
        except requests.RequestException as exc:
            logger.error("[TelegramNotify] Request failed: %s", exc)

    import threading
    t = threading.Thread(target=_send, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Telegram webhook — receives updates FROM Telegram
# ---------------------------------------------------------------------------
# PythonAnywhere note: async views require Django 3.1+ with ASGI.  On the
# free/paid WSGI tier the async view is run via asyncio.run() by Django's
# ASGIHandler.  If you are on a pure WSGI setup and async views are not
# supported, replace the async def with a sync def and use
# asyncio.run(application.process_update(update)) inside a try/except.
# ---------------------------------------------------------------------------

@csrf_exempt
def telegram_webhook(request):
    """
    Receives Telegram webhook POST requests.

    Design goals for PythonAnywhere / free-tier hosting:
    - Always returns a 200 JSON response within milliseconds so Telegram
      does not retry and does not mark the webhook as failing (503).
    - Heavy processing (bot logic) is offloaded to a daemon thread so the
      WSGI worker is freed immediately.
    - @csrf_exempt is required — Telegram cannot send a Django CSRF token.
    """
    if request.method != "POST":
        return JsonResponse({"ok": False, "error": "Only POST allowed."}, status=405)

    token = _get_telegram_bot_token()
    if not token:
        logger.error("[TelegramWebhook] TELEGRAM_BOT_TOKEN is not configured.")
        # Return 200 so Telegram stops retrying — the error is on our side.
        return JsonResponse({"ok": True, "warning": "Bot not configured."})

    # Parse body immediately (fast, in-thread)
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.warning("[TelegramWebhook] Invalid JSON payload: %s", exc)
        return JsonResponse({"ok": False, "error": "Invalid JSON."}, status=400)

    # Offload bot processing to a background thread so we can return 200
    # to Telegram within milliseconds (Telegram requires < 5 s response).
    def _process():
        import asyncio
        try:
            from telegram import Update
            from telegram.ext import Application

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def _run():
                app = Application.builder().token(token).build()
                await app.initialize()
                update = Update.de_json(payload, app.bot)
                if update:
                    await app.process_update(update)
                await app.shutdown()

            loop.run_until_complete(_run())
        except Exception:
            logger.exception("[TelegramWebhook] Background processing failed.")
        finally:
            try:
                loop.close()
            except Exception:
                pass

    import threading
    threading.Thread(target=_process, daemon=True).start()

    # Telegram only cares that we return 200 quickly.
    return JsonResponse({"ok": True})


# --- Social Authentication Views ---

def google_login(request):
    """Redirect to Google OAuth login."""
    from allauth.socialaccount.providers.google.views import GoogleOAuth2View
    from allauth.socialaccount.providers.google.provider import GoogleProvider
    
    provider = GoogleProvider(request)
    app = provider.app
    if not app or not app.client_id:
        messages.error(request, "Google login is not configured. Please contact admin.")
        return redirect('login')
    
    # Redirect to allauth's Google login
    return redirect('/accounts/google/login/?process=login')


def facebook_login(request):
    """Redirect to Facebook OAuth login."""
    from allauth.socialaccount.providers.facebook.provider import FacebookProvider
    
    provider = FacebookProvider(request)
    try:
        app = provider.app
        if not app or not app.client_id:
            messages.error(request, "Facebook login is not configured. Please contact admin.")
            return redirect('login')
    except:
        messages.error(request, "Facebook login is not configured. Please contact admin.")
        return redirect('login')
    
    return redirect('/accounts/facebook/login/?process=login')


def telegram_login(request):
    """Redirect to Telegram OAuth login."""
    # Telegram login via allauth
    return redirect('/accounts/telegram/login/?process=login')


def social_signup_complete(request):
    """Handle social signup completion - require email verification."""
    if request.user.is_authenticated:
        # User is already logged in via social auth
        # Check if email is verified
        try:
            profile = request.user.profile
            if not profile.is_email_verified:
                # Send OTP and redirect to verification
                _send_email_otp(profile=profile)
                messages.success(request, "Please verify your email to complete registration.")
                return redirect('verify_email_otp')
        except Profile.DoesNotExist:
            pass
        
        # Email is verified, redirect to home
        if request.user.is_superuser:
            return redirect('admin_summary')
        return redirect('user_home')
    
    return redirect('login')
