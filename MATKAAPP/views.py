import json
from django.shortcuts import render, redirect
from django.contrib import messages, auth
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.db import transaction
from django.utils import timezone
from django.db.models import Sum

# Local App Imports
from .models import MatkaNumber, Profile, Wallet, Transaction, Bet

# If you are using Django Rest Framework (DRF)
from rest_framework import generics, permissions
from .serializers import WalletSerializer, TransactionSerializer # Removed the '..'
# Ensure your models are imported

def login_view(request):
    # If user is already logged in, don't show the login page    
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == "POST":
        username = request.POST.get('username')
        password = request.POST.get('password')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('index')
        else:
            messages.error(request, "Invalid username or password.")
            return redirect('login')

    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    messages.info(request, "You have successfully logged out.")
    return redirect('index')

def register_view(request):
    if request.user.is_authenticated:
        return redirect('index')

    if request.method == 'POST':
        name = request.POST.get('name')
        username = request.POST.get('username')
        password = request.POST.get('password')
        mobile = request.POST.get('mobile')
        profile_pic = request.FILES.get('profile_pic')

        # Check if username already exists
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already taken!")
            return render(request, 'register.html')

        # 1. Create User (This triggers the signal in models.py)
        user = User.objects.create_user(
            username=username, 
            password=password,
            first_name=name
        )

        # 2. Update the profile automatically created by the signal
        # Use hasattr check just in case the signal failed
        if hasattr(user, 'profile'):
            profile = user.profile
            profile.mobile = mobile
            if profile_pic:
                profile.profile_pic = profile_pic
            profile.save()

        messages.success(request, "Registration successful! Please login.")
        return redirect('login')

    return render(request, 'register.html')

def index(request):
    """
    Main index page view. 
    Fetches matka_numbers so that the template has data to display.
    """
    matka_numbers = MatkaNumber.objects.all()
    context = {
        'matka_numbers': matka_numbers,
    }
    return render(request, 'index.html', context)

def display(request):
    """
    Standalone display page view.
    Useful if you want to view just the table at /display/
    """
    matka_numbers = MatkaNumber.objects.all()
    context = {
        'matka_numbers': matka_numbers,
    }
    return render(request, 'display.html', context)

def error(request):
    """
    Error page view.
    """
    return render(request, 'error.html')


@login_required
def wallet_balance_api(request):
    # This safely gets the wallet or creates it if it doesn't exist
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    return JsonResponse({
        "balance": float(wallet.balance),
        "username": request.user.username
    })

@login_required
def wallet_history_api(request):
    try:
        wallet = request.user.wallet
        transactions = Transaction.objects.filter(wallet=wallet).order_by('-created_at')[:10]
        data = [
            {
                "amount": float(t.amount),
                "type": t.txn_type,
                "description": t.description,
                "date": t.created_at.strftime("%d %b, %H:%M")
            } for t in transactions
        ]
        return JsonResponse({"history": data})
    except Wallet.DoesNotExist:
        return JsonResponse({"history": [], "error": "No wallet found"})
    
@login_required
def single(request):
    markets = MatkaNumber.objects.all()  # Fetch markets to populate the dropdown
    return render(request, 'single.html', {'markets': markets})

@login_required
def jodi(request):
    markets = MatkaNumber.objects.all()
    return render(request, 'jodi.html', {'markets': markets})



@login_required
def bet_history(request):
    # Fetch all bets for the CURRENT logged-in user
    bets = Bet.objects.filter(user=request.user).order_by('-created_at')
    
    # Debug: This will show in your terminal how many bets were found
    print(f"DEBUG: Found {bets.count()} bets for user {request.user.username}")

    # Calculate Summary Stats for the stat-grid
    total_investment = bets.aggregate(Sum('amount'))['amount__sum'] or 0
    total_won = bets.filter(status='WIN').aggregate(Sum('win_amount'))['win_amount__sum'] or 0

    context = {
        'user_bets': bets,  # MUST match the {% if user_bets %} in your HTML
        'total_investment': total_investment,
        'total_won': total_won,
    }
    return render(request, 'bet_history.html', context)


@login_required
def place_bet(request):
    if request.method == "POST":
        # 1. Get data from the frontend
        market = request.POST.get('market')
        game_type = request.POST.get('game_type')
        
        try:
            # Parse the incoming JSON bets
            bets_json = request.POST.get('bets_json')
            bets_data = json.loads(bets_json) # e.g., {"12": 10}

            # --- DECIMAL VALIDATION START ---
            for num, amt in bets_data.items():
                # Convert to float first to safely check
                try:
                    amount_float = float(amt)
                    # If the float value is not equal to its integer version, it's a decimal
                    if amount_float != int(amount_float):
                        return JsonResponse({
                            "status": "error", 
                            "message": f"Invalid amount for number {num}. Decimals are not allowed!"
                        })
                    
                    # Also ensure they aren't trying to bet negative numbers
                    if amount_float <= 0:
                        return JsonResponse({
                            "status": "error", 
                            "message": "Bet amount must be greater than zero."
                        })
                except (ValueError, TypeError):
                    return JsonResponse({"status": "error", "message": "Invalid number format."})
            # --- DECIMAL VALIDATION END ---

            # Calculate total points after we know they are all integers
            total_points = sum(int(float(v)) for v in bets_data.values())

            # 2. Database Transaction (Atomic)
            with transaction.atomic():
                # Lock the wallet row to prevent double-spending
                wallet = Wallet.objects.select_for_update().get(user=request.user)

                if wallet.balance < total_points:
                    return JsonResponse({"status": "error", "message": "Insufficient Balance"})

                # A. Deduct Balance
                wallet.balance -= total_points
                wallet.save()

                # B. Create Transaction Record
                Transaction.objects.create(
                    wallet=wallet,
                    amount=total_points,
                    txn_type='BET_PLACED',
                    description=f"Played {game_type} on {market}"
                )

                # C. Create individual Bet records
                for num, amt in bets_data.items():
                    amt_int = int(float(amt))
                    if amt_int > 0:
                        Bet.objects.create(
                            user=request.user,
                            game_type=game_type,
                            market_name=market,
                            number=num,
                            amount=amt_int
                        )

                return JsonResponse({
                    "status": "success", 
                    "message": "Bet placed successfully!",
                    "new_balance": float(wallet.balance)
                })

        except json.JSONDecodeError:
            return JsonResponse({"status": "error", "message": "Invalid bet data format."})
        except Exception as e:
            return JsonResponse({"status": "error", "message": str(e)})

    return JsonResponse({"status": "error", "message": "Invalid request method."})


@login_required
def admin_summary(request):
    if not request.user.is_staff:
        return render(request, "404.html") # Only allow admins

    today = timezone.now().date()
    
    # 1. Get Total Collection per Market for Today
    market_totals = Bet.objects.filter(created_at__date=today).values('market_name')\
        .annotate(total_collected=Sum('amount')).order_by('-total_collected')

    # 2. Get the "Heavy Loads" (Which numbers have the most money on them)
    # This helps you see your potential payout risk
    heavy_bets = Bet.objects.filter(created_at__date=today).values('market_name', 'number')\
        .annotate(number_total=Sum('amount')).order_by('-number_total')[:10]

    context = {
        'market_totals': market_totals,
        'heavy_bets': heavy_bets,
        'today': today
    }
    return render(request, 'admin_summary.html', context)

@login_required
def declare_result(request):
    if not request.user.is_staff:
        return redirect('home')

    if request.method == "POST":
        market = request.POST.get('market')
        winning_num = request.POST.get('winning_number')
        
        # Define Payout Rates (You can change these)
        rates = {
            'SINGLE': 9,       # 10 ka 90
            'JODI': 95,       # 10 ka 950
            'SINGLE_PATTI': 140 # 10 ka 1400
        }

        # 1. Find all PENDING bets for this market and number
        winning_bets = Bet.objects.filter(
            market_name=market, 
            number=winning_num, 
            status='PENDING'
        )

        # 2. Process Winners
        winners_count = 0
        with transaction.atomic():
            for bet in winning_bets:
                multiplier = rates.get(bet.game_type, 9)
                win_amount = bet.amount * multiplier
                
                # Update User Wallet
                wallet = Wallet.objects.select_for_update().get(user=bet.user)
                wallet.balance += win_amount
                wallet.save()

                # Record Win Transaction
                Transaction.objects.create(
                    wallet=wallet,
                    amount=win_amount,
                    txn_type='WINNING',
                    description=f"Won {bet.game_type} on {market} (Num: {winning_num})"
                )

                # Mark Bet as WIN
                bet.status = 'WIN'
                bet.save()
                winners_count += 1

            # 3. Mark all other PENDING bets for THIS market as LOSS
            Bet.objects.filter(market_name=market, status='PENDING').update(status='LOSS')

        messages.success(request, f"Result Declared! {winners_count} winners paid for {market}.")
        return redirect('admin_summary')

    # Get unique market names from your existing bets to show in dropdown
    markets = Bet.objects.values_list('market_name', flat=True).distinct()
    return render(request, 'declare_result.html', {'markets': markets})



class WalletBalanceView(generics.RetrieveAPIView):
    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.wallet

class TransactionHistoryView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Transaction.objects.filter(wallet=self.request.user.wallet).order_by('-created_at')
    
    
@login_required
def get_wallet_balance(request):
    try:
        wallet = Wallet.objects.get(user=request.user)
        return JsonResponse({"balance": float(wallet.balance)})
    except Wallet.DoesNotExist:
        return JsonResponse({"balance": 0.00})
    
from django.utils import timezone

@login_required
def single_pathi(request):
    markets = MatkaNumber.objects.all()
    
    # Complete Single Patti Chart Mapping (Standard)
    patti_groups = {
        "1": ["128", "137", "146", "236", "245", "290", "380", "470", "489", "560", "678", "579"],
        "2": ["129", "138", "147", "156", "237", "246", "345", "390", "480", "570", "679", "589"],
        "3": ["120", "139", "148", "157", "238", "247", "256", "346", "490", "580", "670", "689"],
        "4": ["130", "149", "158", "167", "239", "248", "257", "347", "356", "590", "680", "789"],
        "5": ["140", "159", "168", "177", "230", "249", "258", "267", "348", "357", "456", "690"],
        "6": ["123", "150", "169", "178", "240", "259", "268", "349", "358", "367", "457", "790"],
        "7": ["124", "160", "179", "232", "250", "269", "278", "340", "359", "368", "458", "467"],
        "8": ["125", "134", "170", "189", "260", "279", "350", "369", "378", "459", "468", "567"],
        "9": ["126", "135", "180", "190", "270", "289", "360", "379", "450", "469", "478", "568"],
        "0": ["127", "136", "145", "190", "280", "299", "370", "389", "460", "479", "569", "578"],
    }
    
    context = {
        'markets': markets,
        'patti_groups': patti_groups,
        'today_date': timezone.now().strftime("%d %b %Y")
    }
    return render(request, 'single_pathi.html', context)

@login_required
def double_pathi(request):
    markets = MatkaNumber.objects.all()
    # Standard Double Patti Chart (2 digits repeat)
    double_groups = {
        "1": ["100", "119", "155", "227", "335", "344", "399", "588", "669"],
        "2": ["110", "200", "228", "255", "336", "444", "499", "660", "688", "778"],
        "3": ["111", "229", "300", "337", "355", "445", "599", "779", "788", "887"],
        "4": ["112", "220", "338", "400", "446", "455", "699", "770", "888", "996"],
        "5": ["113", "122", "339", "447", "500", "555", "799", "889", "880", "997"],
        "6": ["114", "233", "448", "556", "600", "664", "899", "998", "990"],
        "7": ["115", "223", "331", "449", "557", "665", "700", "773", "999", "007"],
        "8": ["116", "224", "332", "440", "558", "666", "774", "800", "882", "990"],
        "9": ["117", "225", "333", "441", "559", "667", "775", "883", "900", "991"],
        "0": ["118", "226", "334", "442", "550", "668", "776", "884", "992"],
    }
    context = {
        'markets': markets,
        'patti_groups': double_groups,
        'game_title': 'DOUBLE PATTI',
        'game_type': 'DOUBLE_PATTI',
        'today_date': timezone.now().strftime("%d %b %Y")
    }
    return render(request, 'single_pathi.html', context)

@login_required
def tripple_pathi(request):
    markets = MatkaNumber.objects.all()
    # Triple Patti (All three digits same)
    triple_groups = {
        "All": ["000", "111", "222", "333", "444", "555", "666", "777", "888", "999"]
    }
    context = {
        'markets': markets,
        'patti_groups': triple_groups,
        'game_title': 'TRIPPLE PATTI',
        'game_type': 'TRIPPLE_PATTI',
        'today_date': timezone.now().strftime("%d %b %Y")
    }
    return render(request, 'single_pathi.html', context)

@login_required
def wallet_balance_api(request):
    wallet, created = Wallet.objects.get_or_create(user=request.user)
    return JsonResponse({
        "balance": float(wallet.balance)
    })