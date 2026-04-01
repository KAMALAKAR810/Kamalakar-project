from django.contrib import admin
from django.utils import timezone
from .models import Profile, Wallet, Market, Bet, Transaction, RegistrationCounter, Message, Notification, PaymentSettings, WithdrawalRequest, DepositRequest, UserActivity, SiteSettings


@admin.register(UserActivity)
class UserActivityAdmin(admin.ModelAdmin):
    list_display = ('user', 'activity_type', 'created_at')
    list_filter = ('activity_type', 'created_at')
    search_fields = ('user__username', 'description')


# --- INLINES ---

class TransactionInline(admin.TabularInline):
    model = Transaction
    extra = 0
    readonly_fields = ('amount', 'txn_type', 'description', 'created_at')
    can_delete = False


# --- ADMIN MODELS ---

@admin.register(Market)
class MarketAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'open_start_time', 'open_end_time',
        'close_start_time', 'close_end_time', 'get_status'
    )
    list_editable = (
        'open_start_time', 'open_end_time',
        'close_start_time', 'close_end_time'
    )
    # FIX: 'name' is a CharField — not valid for list_filter (causes Django warning).
    # Use search_fields for text search instead.
    search_fields = ('name',)

    def get_status(self, obj):
        now = timezone.localtime()
        if obj.open_start_time and obj.open_end_time:
            if obj.open_start_time <= now <= obj.open_end_time:
                return "✅ OPEN ACTIVE"
        if obj.close_start_time and obj.close_end_time:
            if obj.close_start_time <= now <= obj.close_end_time:
                return "✅ CLOSE ACTIVE"
        return "❌ CLOSED"

    get_status.short_description = 'Betting Status'

    fieldsets = (
        ('Market Identity', {'fields': ('name',)}),
        ('Open Section (Morning)', {
            'fields': (
                ('open_start_time', 'open_end_time'),
                ('open_patti', 'open_single')
            )
        }),
        ('Close Section (Evening)', {
            'fields': (
                ('close_start_time', 'close_end_time'),
                ('close_patti', 'close_single')
            )
        }),
    )


@admin.register(Bet)
class BetAdmin(admin.ModelAdmin):
    list_display = (
        'user', 'market', 'game_type', 'session',
        'number', 'amount', 'date', 'status'
    )
    list_filter = ('date', 'market', 'game_type', 'status')
    search_fields = ('user__username', 'number')
    readonly_fields = ('user_id_str', 'created_at')


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'updated_at')
    search_fields = ('user__username', 'user__profile__mobile')
    inlines = [TransactionInline]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('wallet', 'amount', 'txn_type', 'created_at')
    list_filter = ('txn_type', 'created_at')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'user_code', 'mobile', 'created_at')
    search_fields = ('user__username', 'mobile', 'user_code')


@admin.register(RegistrationCounter)
class RegistrationCounterAdmin(admin.ModelAdmin):
    list_display = ('id', 'last_number')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'receiver', 'content', 'created_at', 'is_read')
    list_filter = ('created_at', 'is_read')
    search_fields = ('content', 'sender__username', 'receiver__username')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('title', 'message', 'user__username')


@admin.register(PaymentSettings)
class PaymentSettingsAdmin(admin.ModelAdmin):
    list_display = ('upi_id', 'is_active', 'updated_at')
    list_editable = ('is_active',)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'is_captcha_enabled', 'updated_at')
    list_editable = ('is_captcha_enabled',)
    list_display_links = ('id',)


@admin.register(DepositRequest)
class DepositRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'utr_number', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'utr_number')


@admin.register(WithdrawalRequest)
class WithdrawalRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'upi_id', 'mobile_number', 'bank_account')
