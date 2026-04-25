def axes_whitelist(request, username, ip_address, **kwargs):
    """
    Exempt staff/superusers from django-axes lockouts.
    This prevents admins from getting locked while still protecting normal users.
    """
    if not username:
        return False

    try:
        from django.contrib.auth import get_user_model

        User = get_user_model()
        user = User.objects.filter(username__iexact=username).only("is_staff", "is_superuser").first()
        if not user:
            return False
        return bool(user.is_staff or user.is_superuser)
    except Exception:
        # Fail closed: if anything goes wrong, do not whitelist.
        return False

