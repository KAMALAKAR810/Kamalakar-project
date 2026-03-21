import json
import re
from datetime import timedelta

from django.shortcuts import render, redirect
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
from django.db.models import Sum
from django.utils import timezone

from rest_framework import generics, permissions
from .models import Bet, Transaction, Market, Wallet, Profile, RegistrationCounter
from .serializers import WalletSerializer, TransactionSerializer

def _markets_betting_payload():
    """Per-market OPEN/CLOSE windows for UI locks (matches Market.is_betting_allowed)."""
    return [
        {
            "id": m.id,
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

def login_view(request):
    if request.user.is_authenticated:
        return redirect('index')
    if request.method == "POST":
        u = request.POST.get('username')
        p = request.POST.get('password')
        user = authenticate(request, username=u, password=p)
        if user:
            login(request, user)
            return redirect('index')
        messages.error(request, "Invalid username or password.")
    return render(request, 'login.html')


def logout_view(request):
    logout(request)
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
    if request.method == 'POST':
        # Honeypot — bots often fill hidden fields
        if request.POST.get("website", "").strip():
            messages.error(request, "Registration could not be completed.")
            return render(request, 'register.html')

        name = (request.POST.get('name') or '').strip()
        user_n = (request.POST.get('username') or '').strip()
        psw = request.POST.get('password') or ''
        psw2 = request.POST.get('password2') or ''
        mob = request.POST.get('mobile') or ''

        if not name or not user_n:
            messages.error(request, "Full name and username are required.")
            return render(request, 'register.html')

        if psw != psw2:
            messages.error(request, "Passwords do not match.")
            return render(request, 'register.html')

        mobile_digits, mobile_err = _normalize_indian_mobile(mob)
        if mobile_err:
            messages.error(request, mobile_err)
            return render(request, 'register.html')

        if User.objects.filter(username__iexact=user_n).exists():
            messages.error(request, "Username already taken.")
            return render(request, 'register.html')

        if Profile.objects.filter(mobile=mobile_digits).exists():
            messages.error(request, "This mobile number is already registered.")
            return render(request, 'register.html')

        candidate = User(username=user_n, first_name=name)
        try:
            validate_password(psw, user=candidate)
        except ValidationError as e:
            for msg in e.messages:
                messages.error(request, msg)
            return render(request, 'register.html')

        try:
            with db_transaction.atomic():
                user = User.objects.create_user(username=user_n, password=psw, first_name=name)
                user_code = RegistrationCounter.next_user_code()
                profile = Profile.objects.select_for_update().get(user=user)
                profile.mobile = mobile_digits
                profile.user_code = user_code
                pic = request.FILES.get("profile_pic")
                if pic:
                    profile.profile_pic = pic
                profile.save()
                Wallet.objects.get_or_create(user=user)
        except IntegrityError:
            messages.error(request, "Username or mobile is already in use. Please try again.")
            return render(request, 'register.html')

        messages.success(
            request,
            f"Registration successful! Welcome To AstroWebsite {user_n}. You can log in now.",
        )
        return redirect('login')
    return render(request, 'register.html')


# --- BASIC PAGES ---

def index(request):
    return render(request, 'index.html', {'markets': Market.objects.all()})


def display(request):
    return render(request, 'display_page.html', {'markets': Market.objects.all()})


def error(request):
    return render(request, 'error.html')


# --- UNIFIED BET PLACEMENT ENGINE ---

@login_required
@db_transaction.atomic
# FIX: Decorator now uses aliased 'db_transaction' — no name collision.
def place_bet(request):
    if request.method != "POST":
        return JsonResponse({"status": "error", "message": "Method not allowed."}, status=405)

    market_id  = request.POST.get('market')
    game_type  = request.POST.get('game_type')
    session    = request.POST.get('session')
    bets_json  = request.POST.get('bets_json')

    try:
        market = Market.objects.get(id=market_id)
        bets_data = json.loads(bets_json)

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

        try:
            prof = request.user.profile
            uid_display = prof.user_code if prof.user_code else str(request.user.id)
        except Profile.DoesNotExist:
            uid_display = str(request.user.id)
        for number, amount in bets_data.items():
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
    bets = Bet.objects.filter(user=request.user).order_by('-created_at')
    return render(request, 'bet_history.html', {'user_bets': bets})


# --- ADMIN VIEWS ---

@user_passes_test(lambda u: u.is_staff)
def admin_summary(request):
    bets = Bet.objects.all()
    total_inv = bets.aggregate(Sum("amount"))["amount__sum"] or 0
    return render(request, "admin_summary.html", {"total_inv": total_inv})


@user_passes_test(lambda u: u.is_staff)
def manage_markets(request):
    return render(request, "manage_markets.html", {"markets": Market.objects.all()})


@user_passes_test(lambda u: u.is_staff)
def market_bets(request):
    return render(request, "market_bets.html", {"bets": Bet.objects.all()})


# --- REST API CLASSES ---

class WalletBalanceView(generics.RetrieveAPIView):
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.wallet


class TransactionHistoryView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Transaction.objects.filter(
            wallet=self.request.user.wallet
        ).order_by('-created_at')
