from decimal import Decimal
import json
import re
import random
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
from django.db.models import Sum, Q
from django.utils import timezone

from .models import Bet, Transaction, Market, Wallet, Profile, Message

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
    if not request.user.is_authenticated or not request.user.is_superuser:
        return {}
    new_users = Profile.objects.filter(is_new=True).count()
    unread_msgs = Message.objects.filter(receiver__is_superuser=True, is_read=False).count()
    return {'new_users': new_users, 'unread_msgs': unread_msgs}


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
    
    if request.method == 'POST':
        # 1. Detect if this is an AJAX JSON request or a standard Form POST
        is_ajax = request.content_type == 'application/json' or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        
        if is_ajax:
            try:
                data = json.loads(request.body)
                user_n = data.get('username')
                psw = data.get('password')
            except json.JSONDecodeError:
                return JsonResponse({'status': 'error', 'message': 'Invalid JSON data.'})
        else:
            user_n = request.POST.get('username')
            psw = request.POST.get('password')

        user = authenticate(request, username=user_n, password=psw)
        
        if user is not None:
            login(request, user)
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
            return render(request, 'login.html')

    return render(request, 'login.html')


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
                # Profile and user_code are automatically created via signals.
                profile = Profile.objects.select_for_update().get(user=user)
                profile.mobile = mobile_digits
                pic = request.FILES.get("profile_pic")
                if pic:
                    profile.profile_pic = pic
                profile.save()

                # Wallet is also automatically created via signals.

                # Send automatic welcome message if superuser exists
                admin_user = User.objects.filter(is_superuser=True).first()
                if admin_user:
                    welcome_text = f'Hi {user_n}, welcome to MatkaPlay!'
                    Message.objects.create(sender=admin_user, receiver=user, content=welcome_text)

        except IntegrityError:
            messages.error(request, "Username or mobile is already in use. Please try again.")
            return render(request, 'register.html')

        messages.success(
            request,
            f"Registration successful! Welcome To MatkaPlay {user_n}. You can log in now.",
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

@user_passes_test(lambda u: u.is_superuser)
def admin_bet_history(request):
    """Admin view for all user bet history with specific columns."""
    bets = Bet.objects.select_related('user', 'user__profile', 'market').all().order_by('-created_at')
    return render(request, 'admin_bet_history.html', {'bets': bets})


@user_passes_test(lambda u: u.is_superuser)
def declare_result(request):
    """Admin view to declare market results."""
    markets = Market.objects.all()
    if request.method == 'POST':
        market_id = request.POST.get('market_id')
        op = request.POST.get('open_patti')
        os = request.POST.get('open_single')
        cp = request.POST.get('close_patti')
        cs = request.POST.get('close_single')
        
        market = Market.objects.get(id=market_id)
        market.open_patti = op
        market.open_single = os
        market.close_patti = cp
        market.close_single = cs
        market.save()
        
        # Calculate winners for this market
        calculate_winners(market)
        
        messages.success(request, f"Result declared for {market.name} successfully!")
        return redirect('declare_result')
        
    return render(request, 'admin_declare_result.html', {'markets': markets})


def calculate_winners(market):
    """Business logic to compare admin result with user bets."""
    bets = Bet.objects.filter(market=market, status='PENDING')
    
    for bet in bets:
        is_winner = False
        win_ratio = 0
        
        # 1. Open Patti check (Matches for Single Patti, Double Patti, Triple Patti)
        if bet.session == 'OPEN' and bet.game_type in ['SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']:
            if bet.number == market.open_patti:
                is_winner = True
                if bet.game_type == 'SINGLE_PATTI': win_ratio = 1300
                elif bet.game_type == 'DOUBLE_PATTI': win_ratio = 2600
                elif bet.game_type == 'TRIPLE_PATTI': win_ratio = 7000
        
        # 2. Open Single check
        elif bet.session == 'OPEN' and bet.game_type == 'SINGLE':
            if bet.number == market.open_single:
                is_winner = True
                win_ratio = 9
                
        # 3. Close Single check
        elif bet.session == 'CLOSE' and bet.game_type == 'SINGLE':
            if bet.number == market.close_single:
                is_winner = True
                win_ratio = 9
                
        # 4. Close Patti check (Matches for Single Patti, Double Patti, Triple Patti)
        elif bet.session == 'CLOSE' and bet.game_type in ['SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']:
            if bet.number == market.close_patti:
                is_winner = True
                if bet.game_type == 'SINGLE_PATTI': win_ratio = 1300
                elif bet.game_type == 'DOUBLE_PATTI': win_ratio = 2600
                elif bet.game_type == 'TRIPLE_PATTI': win_ratio = 7000
                
        # 5. Jodi check (Matches against OpenSingle + CloseSingle)
        elif bet.game_type == 'JODI':
            # Jodi number is OpenSingle + CloseSingle
            jodi_result = f"{market.open_single}{market.close_single}"
            if bet.number == jodi_result:
                is_winner = True
                win_ratio = 90
        
        if is_winner:
            bet.status = 'WIN'
            bet.win_amount = float(bet.amount) * win_ratio
            # Credit to wallet
            with db_transaction.atomic():
                wallet = bet.user.wallet
                wallet.balance += Decimal(str(bet.win_amount))
                wallet.save()
                
                # Record the transaction
                Transaction.objects.create(
                    wallet=wallet,
                    amount=Decimal(str(bet.win_amount)),
                    txn_type='WIN',
                    description=f"WIN: {bet.game_type} - {market.name} ({bet.number})"
                )
        else:
            bet.status = 'LOSS'
            bet.win_amount = 0
            
        bet.save()


@user_passes_test(lambda u: u.is_superuser)
def winners_list(request):
    """Display the PASS (Winner) table with filters."""
    game_type = request.GET.get('game_type', 'ALL')
    market_id = request.GET.get('market', 'ALL')
    session = request.GET.get('session', 'ALL')
    
    winners = Bet.objects.filter(status='WIN').select_related('user', 'user__profile', 'market')
    
    if game_type != 'ALL':
        winners = winners.filter(game_type=game_type)
    if market_id != 'ALL':
        winners = winners.filter(market_id=market_id)
    if session != 'ALL':
        winners = winners.filter(session=session)
        
    # Order by winning amount descending
    winners = winners.order_by('-win_amount')
    
    markets = Market.objects.all()
    
    # Get the latest result for display if market is selected
    latest_result = None
    if market_id != 'ALL':
        latest_result = Market.objects.get(id=market_id)

    return render(request, 'admin_winners.html', {
        'winners': winners,
        'markets': markets,
        'latest_result': latest_result,
        'selected_game_type': game_type,
        'selected_market_id': market_id,
        'selected_session': session
    })


@user_passes_test(lambda u: u.is_superuser)
def organize_data_view(request):
    """Admin view for organized market data filtering."""
    markets = Market.objects.all()
    selected_market_id = request.GET.get('market')
    selected_session = request.GET.get('session', 'OPEN')
    
    game_data = {gt: [] for gt in ['SINGLE', 'JODI', 'SINGLE_PATTI', 'DOUBLE_PATTI', 'TRIPLE_PATTI']}
    
    if selected_market_id:
        market = Market.objects.get(id=selected_market_id)
        bets = Bet.objects.filter(market=market, session=selected_session)
        
        from django.db.models import Sum, Count
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
        'table_rows': table_rows,
    })


@user_passes_test(lambda u: u.is_staff)
def admin_summary(request):
    bets = Bet.objects.all()
    total_inv = bets.aggregate(Sum("amount"))["amount__sum"] or 0
    return render(request, "admin_summary.html", {"total_inv": total_inv})


@user_passes_test(lambda u: u.is_superuser)
def admin_user_management(request):
    """Page 1: Message new users and see verification status."""
    profiles = Profile.objects.select_related('user').all().order_by('-created_at')
    # Mark all as seen when admin visits this page
    Profile.objects.filter(is_new=True).update(is_new=False)
    return render(request, 'admin_user_management.html', {'profiles': profiles})


@user_passes_test(lambda u: u.is_superuser)
def admin_chat_list(request):
    """Page 2: WhatsApp style chat list."""
    # Get all users who have messaged or been messaged
    users = User.objects.exclude(is_superuser=True).filter(
        Q(received_messages__sender=request.user) | Q(sent_messages__receiver=request.user)
    ).distinct()
    return render(request, 'admin_chat_list.html', {'users': users})


@login_required
def chat_view(request, user_id=None):
    """Unified chat view for User-Admin messaging."""
    if request.user.is_superuser:
        if not user_id:
            return redirect('admin_chat_list')
        other_user = User.objects.get(id=user_id)
        # Mark messages as read when admin opens the chat
        Message.objects.filter(sender=other_user, receiver=request.user, is_read=False).update(is_read=True)
    else:
        # Normal user can only chat with admin
        other_user = User.objects.filter(is_superuser=True).first()
        if not other_user:
            return redirect('error')
        # Mark admin's messages as read when user opens the chat
        Message.objects.filter(sender=other_user, receiver=request.user, is_read=False).update(is_read=True)

    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            Message.objects.create(sender=request.user, receiver=other_user, content=content)
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({'status': 'success'})
            return redirect('chat_view', user_id=other_user.id if request.user.is_superuser else None)

    # Get messages between these two users
    messages_list = Message.objects.filter(
        (Q(sender=request.user) & Q(receiver=other_user)) |
        (Q(sender=other_user) & Q(receiver=request.user))
    ).order_by('created_at')

    return render(request, 'chat.html', {
        'other_user': other_user,
        'chat_messages': messages_list
    })


@user_passes_test(lambda u: u.is_superuser)
def send_welcome_msg(request, user_id):
    """Ajax endpoint to send welcome message."""
    user = User.objects.get(id=user_id)
    content = f"Hi {user.username}, welcome to MatkaPlay!"
    Message.objects.get_or_create(sender=request.user, receiver=user, content=content)
    return JsonResponse({'status': 'success'})


@login_required
def payment_page(request):
    """Payment form with QR popup."""
    # Ensure profile exists to avoid RelatedObjectDoesNotExist
    profile, created = Profile.objects.get_or_create(user=request.user)
    return render(request, 'payment.html', {
        'username': request.user.username,
        'mobile': profile.mobile or "Not set",
        'user_code': profile.user_code or "N/A",
        'upi_id': '8217228766@ibl'
    })


@user_passes_test(lambda u: u.is_staff)
def manage_markets(request):
    return render(request, "manage_markets.html", {"markets": Market.objects.all()})


@user_passes_test(lambda u: u.is_staff)
def market_bets(request):
    return render(request, "market_bets.html", {"bets": Bet.objects.all()})
