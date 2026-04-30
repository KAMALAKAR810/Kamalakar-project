import re
from django.core.cache import cache

from .models import Message, Notification, Profile

_WHATSAPP_CACHE_KEY = "admin_whatsapp_number"
_WHATSAPP_CACHE_TTL = 300  # 5 minutes


def _normalize_whatsapp_number(value):
    digits = re.sub(r"\D", "", value or "")
    return digits


def admin_ui_context(request):
    context = {}

    if hasattr(request, "user") and request.user.is_authenticated:
        try:
            wallet_balance = request.user.wallet.balance
        except Exception:
            wallet_balance = 0

        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
        if request.user.is_superuser:
            context.update({
                "new_users": Profile.objects.filter(is_new=True).exists(),
                "unread_msgs": unread_count,
                "wallet_balance": wallet_balance,
            })
        else:
            context.update({
                "unread_notifs": Notification.objects.filter(user=request.user, is_read=False).count(),
                "unread_msgs": unread_count,
                "wallet_balance": wallet_balance,
            })

    # Cache the admin WhatsApp number to avoid a DB hit on every request
    whatsapp_number = cache.get(_WHATSAPP_CACHE_KEY)
    if whatsapp_number is None:
        admin_profile = (
            Profile.objects.select_related("user")
            .filter(user__is_superuser=True)
            .order_by("user_id")
            .first()
        )
        whatsapp_number = _normalize_whatsapp_number(
            getattr(admin_profile, "support_whatsapp_number", "")
        ) or "918217228765"
        cache.set(_WHATSAPP_CACHE_KEY, whatsapp_number, _WHATSAPP_CACHE_TTL)

    context.update({
        "support_whatsapp_number": whatsapp_number,
        "support_whatsapp_url": f"https://wa.me/{whatsapp_number}",
    })
    return context
