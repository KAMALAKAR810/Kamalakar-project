import re

from .models import Message, Notification, Profile


def _normalize_whatsapp_number(value):
    digits = re.sub(r"\D", "", value or "")
    return digits


def admin_ui_context(request):
    context = {}

    if hasattr(request, "user") and request.user.is_authenticated:
        unread_count = Message.objects.filter(receiver=request.user, is_read=False).count()
        if request.user.is_superuser:
            context.update({
                "new_users": Profile.objects.filter(is_new=True).exists(),
                "unread_msgs": unread_count,
            })
        else:
            context.update({
                "unread_notifs": Notification.objects.filter(user=request.user, is_read=False).count(),
                "unread_msgs": unread_count,
            })

    admin_profile = (
        Profile.objects.select_related("user")
        .filter(user__is_superuser=True)
        .order_by("user_id")
        .first()
    )
    whatsapp_number = _normalize_whatsapp_number(
        getattr(admin_profile, "support_whatsapp_number", "")
    ) or "918217228765"

    context.update({
        "support_whatsapp_number": whatsapp_number,
        "support_whatsapp_url": f"https://wa.me/{whatsapp_number}",
    })
    return context
