from datetime import datetime, timedelta
from decimal import Decimal
import json
import re
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
# FIX: Renamed import to 'db_transaction' to avoid name collision with the
# local variable 'transaction' used inside place_bet and the Transaction model.
from django.db import transaction as db_transaction
from django.db.models import Sum, Q, Count, Max
from django.utils import timezone
import requests
from django.conf import settings
import base64
try:
    from webauthn import (
        generate_registration_options,
        verify_registration_response,
        generate_authentication_options,
        verify_authentication_response,
        options_to_json,
    )
    from webauthn.helpers.structs import (
        AttestationPreference,
        AuthenticatorSelectionCriteria,
        UserVerificationRequirement,
        AuthenticatorAttachment,
    )
    WEBAUTHN_AVAILABLE = True
except ImportError:
    WEBAUTHN_AVAILABLE = False

from .models import Bet, Transaction, Market, Wallet, Profile, Message, WithdrawalRequest, Notification, MarketHistory, PaymentSettings, DepositRequest, UserActivity, SiteSettings
import uuid

@login_required
def biometric_reg_options(request):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Staff access required'})
    
    if not WEBAUTHN_AVAILABLE:
        return JsonResponse({'status': 'error', 'message': 'WebAuthn library not installed on server'})
    
    try:
        RP_ID = request.get_host().split(':')[0]
        RP_NAME = "MATKA Admin"
        
        # user_id must be bytes
        user_id = str(request.user.id).encode('utf-8')
        
        options = generate_registration_options(
            rp_id=RP_ID,
            rp_name=RP_NAME,
            user_id=user_id,
            user_name=request.user.username,
            attestation=AttestationPreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
        )
        
        request.session['registration_challenge'] = options.challenge.decode('utf-8') if isinstance(options.challenge, bytes) else options.challenge
        
        return JsonResponse(json.loads(options_to_json(options)))
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def biometric_reg_verify(request):
    if not request.user.is_staff or not WEBAUTHN_AVAILABLE:
        return JsonResponse({'status': 'error', 'message': 'Not available'})
    
    try:
        data = json.loads(request.body)
        challenge = request.session.get('registration_challenge')
        if not challenge:
            return JsonResponse({'status': 'error', 'message': 'Challenge not found in session'})
            
        RP_ID = request.get_host().split(':')[0]
        # Robust origin detection
        if request.is_secure():
            ORIGIN = f"https://{request.get_host()}"
        else:
            # Fallback for proxies if is_secure() is not set up correctly
            origin_header = request.headers.get('Origin')
            if origin_header:
                ORIGIN = origin_header
            else:
                ORIGIN = f"http://{request.get_host()}"

        verification = verify_registration_response(
            credential=data,
            expected_challenge=challenge.encode('utf-8') if isinstance(challenge, str) else challenge,
            expected_origin=ORIGIN,
            expected_rp_id=RP_ID,
            require_user_verification=True,
        )
        
        # Save credential data to profile
        profile = request.user.profile
        profile.webauthn_credential = {
            'id': verification.credential_id.decode('utf-8') if isinstance(verification.credential_id, bytes) else verification.credential_id,
            'public_key': base64.b64encode(verification.credential_public_key).decode('utf-8'),
            'sign_count': verification.sign_count,
        }
        profile.save()
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def biometric_auth_options(request):
    if not request.user.is_staff:
        return JsonResponse({'status': 'error', 'message': 'Staff access required'})
        
    if not WEBAUTHN_AVAILABLE:
        return JsonResponse({'status': 'error', 'message': 'WebAuthn library not installed on server'})
    
    try:
        profile = request.user.profile
        if not profile.webauthn_credential:
            return JsonResponse({'status': 'error', 'message': 'No biometric registered'})
        
        RP_ID = request.get_host().split(':')[0]
        
        options = generate_authentication_options(
            rp_id=RP_ID,
            allow_credentials=[{
                'id': profile.webauthn_credential['id'],
                'type': 'public-key',
            }],
            user_verification=UserVerificationRequirement.REQUIRED,
        )
        
        request.session['authentication_challenge'] = options.challenge.decode('utf-8') if isinstance(options.challenge, bytes) else options.challenge
        
        return JsonResponse(json.loads(options_to_json(options)))
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def biometric_auth_verify(request):
    if not request.user.is_staff or not WEBAUTHN_AVAILABLE:
        return JsonResponse({'status': 'error', 'message': 'Not available'})
    
    try:
        data = json.loads(request.body)
        challenge = request.session.get('authentication_challenge')
        if not challenge:
            return JsonResponse({'status': 'error', 'message': 'Challenge not found in session'})
            
        RP_ID = request.get_host().split(':')[0]
        # Robust origin detection
        if request.is_secure():
            ORIGIN = f"https://{request.get_host()}"
        else:
            # Fallback for proxies if is_secure() is not set up correctly
            origin_header = request.headers.get('Origin')
            if origin_header:
                ORIGIN = origin_header
            else:
                ORIGIN = f"http://{request.get_host()}"
                
        profile = request.user.profile
        
        credential = profile.webauthn_credential
        
        verification = verify_authentication_response(
            credential=data,
            expected_challenge=challenge.encode('utf-8') if isinstance(challenge, str) else challenge,
            expected_origin=ORIGIN,
            expected_rp_id=RP_ID,
            credential_public_key=base64.b64decode(credential['public_key']),
            credential_current_sign_count=credential['sign_count'],
            require_user_verification=True,
        )
        
        # Update sign count
        profile.webauthn_credential['sign_count'] = verification.new_sign_count
        profile.save()
        
        # Mark 2FA as verified
        request.session['admin_2fa_verified'] = True
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@login_required
def admin_2fa_view(request):
    if not request.user.is_staff:
        return redirect('index')
    
    if request.session.get('admin_2fa_verified'):
        return redirect('admin:index')
    
    profile = request.user.profile
    
    if request.method == 'POST':
        auth_type = request.POST.get('auth_type')
        
        if auth_type == 'pin':
            pin = request.POST.get('pin')
            if pin == profile.admin_pin:
                request.session['admin_2fa_verified'] = True
                messages.success(request, "2FA Verified successfully!")
                return redirect('admin:index')
            else:
                messages.error(request, "Invalid PIN!")
        
        elif auth_type == 'security_question':
            answer = request.POST.get('answer', '').strip()
            if answer == profile.admin_security_answer:
                request.session['admin_2fa_verified'] = True
                messages.success(request, "2FA Verified successfully!")
                return redirect('admin:index')
            else:
                messages.error(request, "Incorrect answer!")
            
    return render(request, 'admin_2fa.html', {
        'profile': profile
    })

@login_required
@user_passes_test(lambda u: u.is_superuser)
def update_admin_security_view(request):
    profile = request.user.profile
    if request.method == 'POST':
        new_pin = request.POST.get('admin_pin')
        new_question = request.POST.get('admin_security_question')
        new_answer = request.POST.get('admin_security_answer')
        
        if new_pin and len(new_pin) == 6 and new_pin.isdigit():
            profile.admin_pin = new_pin
        
        if new_question:
            profile.admin_security_question = new_question
            
        if new_answer:
            profile.admin_security_answer = new_answer
            
        profile.save()
        messages.success(request, "Security settings updated successfully!")
        return redirect('admin_summary')
        
    return render(request, 'update_admin_security.html', {'profile': profile})

def create_notification(user, title, message):
    Notification.objects.create(user=user, title=title, message=message)

@login_required
def notifications_view(request):
    notifications = request.user.notifications.all()
    # Mark all as read when viewing
    notifications.filter(is_read=False).update(is_read=True)
    return render(request, 'notifications.html', {'notifications': notifications})

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
            
        messages.success(request, f"Withdrawal request for ₹{amount} submitted!")
        return redirect('wallet_history')
        
    return render(request, 'wallet.html')


@login_required
def wallet_history_view(request):
    """User can see their wallet transactions and withdrawal status."""
    transactions = Transaction.objects.filter(wallet=request.user.wallet).order_by('-created_at')
    withdrawals = WithdrawalRequest.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'wallet_history.html', {
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
    return render(request, 'admin_withdrawal_management.html', {'withdrawal_requests': requests})

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


def _get_admin_notifications(request):
    """Context processor for admin notification dots. Must accept 'request'."""
    settings_obj = SiteSettings.objects.first()
    enable_captcha = settings_obj.is_captcha_enabled if settings_obj else True
    
    context = {
        'enable_captcha': enable_captcha
    }
    
    # Safety check: ensure 'user' attribute exists before accessing it
    if hasattr(request, 'user') and request.user.is_authenticated:
        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
        if request.user.is_superuser:
            context.update({
                'new_users': Profile.objects.filter(is_new=True).exists(),
                'unread_msgs': unread_count
            })
        else:
            context.update({
                'unread_notifs': Notification.objects.filter(user=request.user, is_read=False).count(),
                'unread_msgs': unread_count
            })
    return context


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

def login_view(request):
    if request.user.is_authenticated:
        return redirect('index')
    
    settings_obj = SiteSettings.objects.first()
    enable_captcha = settings_obj.is_captcha_enabled if settings_obj else True

    if request.method == 'POST':
        # 1. Detect if this is an AJAX JSON request or a standard Form POST
        is_ajax = request.content_type == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        user_n = request.POST.get('username')
        psw = request.POST.get('password')

        user = authenticate(request, username=user_n, password=psw)
        
        if user is not None:
            # Task 2: Enforce one session per user
            from django.contrib.sessions.models import Session
            try:
                profile = user.profile
                if profile.session_key:
                    Session.objects.filter(session_key=profile.session_key).delete()
            except Profile.DoesNotExist:
                pass

            login(request, user)
            
            # Save the new session key to the profile
            try:
                profile = user.profile
                profile.session_key = request.session.session_key
                profile.save()
            except Profile.DoesNotExist:
                pass

            messages.success(request, f"Welcome back, {user.username}!")
            
            if is_ajax:
                return JsonResponse({'status': 'success'})
            
            # For standard form, handle the 'next' parameter
            next_url = request.GET.get('next') or 'index'
            return redirect(next_url)
        else:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': 'Invalid username or password.'})
            
            messages.error(request, "Invalid username or password.")
            return render(request, 'login.html', {'enable_captcha': enable_captcha})

    return render(request, 'login.html', {'enable_captcha': enable_captcha})


def logout_view(request):
    logout(request)
    messages.success(request, "LOGOUT SUCCESSFUL! You have been safely logged out.")
    return redirect('login')


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


def register_view(request):
    if request.user.is_authenticated:
        return redirect('index')

    settings_obj = SiteSettings.objects.first()
    enable_captcha = settings_obj.is_captcha_enabled if settings_obj else True

    if request.method == 'POST':
        # Honeypot — bots often fill hidden fields
        if request.POST.get("website", "").strip():
            messages.error(request, "Registration could not be completed.")
            return render(request, 'register.html', {'enable_captcha': enable_captcha})

        name = (request.POST.get('name') or '').strip()
        user_n = (request.POST.get('username') or '').strip()
        psw = request.POST.get('password') or ''
        psw2 = request.POST.get('password2') or ''
        mob = request.POST.get('mobile') or ''
        
        if not name or not user_n:
            messages.error(request, "Full name and username are required.")
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        if psw != psw2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        mobile_digits, mobile_err = _normalize_indian_mobile(mob)
        if mobile_err:
            messages.error(request, mobile_err)
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        if User.objects.filter(username__iexact=user_n).exists():
            messages.error(request, "Username already taken.")
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        if Profile.objects.filter(mobile=mobile_digits).exists():
            messages.error(request, "This mobile number is already registered.")
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        candidate = User(username=user_n, first_name=name)
        try:
            validate_password(psw, user=candidate)
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, 'register.html', {
                'name': name, 'username': user_n, 'mobile': mob, 'enable_captcha': enable_captcha
            })

        try:
            with db_transaction.atomic():
                user = User.objects.create_user(username=user_n, password=psw, first_name=name)
                # Profile and user_code are automatically created via signals.
                profile = Profile.objects.select_for_update().get(user=user)
                profile.mobile = mobile_digits
                pic = request.FILES.get("profile_pic")
                if pic:
                    profile.profile_pic = pic
                profile.save()

                # Wallet is also automatically created via signals.

                # Task 8: Send welcome message to user
                admin_user = User.objects.filter(is_superuser=True).first()
                if admin_user:
                    Message.objects.create(
                        sender=admin_user,
                        receiver=user,
                        content="Welcome to ChangeLifeWithNumbers! Play smart, win big."
                    )

        except IntegrityError:
            messages.error(request, "Username or mobile is already in use. Please try again.")
            return render(request, 'register.html', {'enable_captcha': enable_captcha})

        messages.success(
            request,
            f"Registration successful! Welcome to ChangeLifeWithNumbers {user_n}. You can log in now.",
        )
        return redirect('login')
    return render(request, 'register.html', {'enable_captcha': enable_captcha})


# --- BASIC PAGES ---

def error_404(request, exception):
    return render(request, 'error.html', status=404)

def error_500(request):
    return render(request, 'error.html', status=500)

def error_403(request, exception):
    return render(request, 'error.html', status=403)

def error_400(request, exception):
    return render(request, 'error.html', status=400)

def index(request):
    return render(request, 'index.html', {'markets': Market.objects.all()})


def display(request):
    return render(request, 'display_page.html', {'markets': Market.objects.all()})


def error(request):
    return render(request, 'error.html')


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
    return render(request, "single.html", {
        "markets": Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        "game_title": "SINGLE",
        "game_type": "SINGLE",
    })


@login_required
def jodi(request):
    return render(request, 'jodi.html', {
        'markets': Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        'game_title': 'JODI',
        "game_type": "JODI",
    })


@login_required
def single_pathi(request):
    return render(request, "single_pathi.html", {
        "markets": Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        "game_title": "SINGLE PATTI",
        "game_type": "SINGLE_PATTI",
        "patti_groups": SINGLE_PATTI_GROUPS
    })


@login_required
def double_pathi(request):
    return render(request, 'single_pathi.html', {
        'markets': Market.objects.all(),
        "markets_betting": _markets_betting_payload(),
        'game_title': 'DOUBLE PATTI',
        'game_type': 'DOUBLE_PATTI',
        'patti_groups': DOUBLE_PATTI_GROUPS
    })


@login_required
def tripple_pathi(request):
    return render(request, 'single_pathi.html', {
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
    
    return render(request, 'bet_history.html', {
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

    return render(request, 'admin_bet_history.html', {
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
        
    return render(request, 'admin_declare_result.html', {'markets': markets})


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
    return render(request, 'jodi_winners.html', {
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

    return render(request, 'admin_winners.html', {
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

    return render(request, 'organize_data.html', {
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
    
    return render(request, 'admin_report.html', {
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

    return render(request, "admin_summary.html", {
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

    return render(request, 'admin_user_activity.html', {'activities': activities})


@user_passes_test(lambda u: u.is_superuser)
def admin_user_management(request):
    """Page 1: Message new users and see verification status."""
    profiles = Profile.objects.select_related('user').all().order_by('-created_at')
    # Mark all as seen when admin visits this page
    Profile.objects.filter(is_new=True).update(is_new=False)
    return render(request, 'admin_user_management.html', {'profiles': profiles})


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
    
    return render(request, 'admin_chat_list.html', {
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

    return render(request, 'chat.html', {
        'other_user': other_user,
        'grouped_messages': grouped_messages,
        'today_date': timezone.now().date().strftime('%Y-%m-%d'),
        'yesterday_date': (timezone.now() - timedelta(days=1)).date().strftime('%Y-%m-%d'),
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
            
            return render(request, 'payment_qr.html', {
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
        
        return JsonResponse({'status': 'success', 'message': 'UTR submitted successfully! Your wallet will be updated after verification.'})

    # Standard GET: Show initial amount entry form
    profile, _ = Profile.objects.get_or_create(user=request.user)
    return render(request, 'payment.html', {
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

    return render(request, 'admin_payment_management.html', {
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
    
    # Reset market fields to None (allowing re-entry for a new cycle)
    market.collection_date = None
    market.open_start_time = None
    market.open_end_time = None
    market.close_start_time = None
    market.close_end_time = None
    market.open_patti = None
    market.open_single = None
    market.open_declared_at = None
    market.close_patti = None
    market.close_single = None
    market.close_declared_at = None
    market.save()
    
    messages.success(request, f"Market '{market.name}' has been reset and archived successfully.")
    return redirect('manage_markets')


@user_passes_test(lambda u: u.is_superuser)
def market_history_view(request):
    """
    View for admin to see all archived market history.
    """
    history = MarketHistory.objects.select_related('market').all()
    return render(request, 'admin_market_history.html', {'history': history})


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
        oet = request.POST.get('open_end_time')
        cst = request.POST.get('close_start_time')
        cet = request.POST.get('close_end_time')
        
        # Replace 'T' with space if present for some DB backends, 
        # though Django usually handles datetime-local format.
        def parse_dt(dt_str):
            if dt_str:
                return dt_str.replace('T', ' ')
            return None

        Market.objects.create(
            name=name,
            collection_date=parse_dt(coll_date),
            open_start_time=parse_dt(ost),
            open_end_time=parse_dt(oet),
            close_start_time=parse_dt(cst),
            close_end_time=parse_dt(cet)
        )
        messages.success(request, f"Market '{name}' created successfully!")
        return redirect('manage_markets')
        
    return render(request, "manage_markets.html", {"markets": Market.objects.all().order_by('name')})


@user_passes_test(lambda u: u.is_staff)
def market_bets(request):
    return render(request, "market_bets.html", {"bets": Bet.objects.all()})



from django.shortcuts import render
from .forms import MyContactForm

def contact_view(request):
    settings_obj = SiteSettings.objects.first()
    enable_captcha = settings_obj.is_captcha_enabled if settings_obj else True
    
    if request.method == 'POST':
        form = MyContactForm(request.POST)
        if form.is_valid():
            # If we are here, Google has already confirmed they are human (if enabled)!
            return render(request, 'success.html')
    else:
        form = MyContactForm()
    
    return render(request, 'contact.html', {'form': form, 'enable_captcha': enable_captcha})
