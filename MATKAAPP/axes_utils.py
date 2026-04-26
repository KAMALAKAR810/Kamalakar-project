def axes_whitelist(request, credentials=None, *args, **kwargs):
    """
    Exempt staff/superusers from django-axes lockouts.
    This prevents admins from getting locked while still protecting normal users.
    """

    # django-axes has changed the whitelist callable signature across versions:
    # - older: (request, username, ip_address, **kwargs)
    # - newer: (request, credentials)
    #
    # To stay compatible, accept both and extract the username if present.
    username = None
    if isinstance(credentials, str):
        # Called as (request, username, ip_address, ...)
        username = credentials
    elif isinstance(credentials, dict):
        # Called as (request, credentials)
        username = credentials.get("username") or credentials.get("email") or credentials.get("user")

    # Some integrations might pass username as a kwarg.
    if not username:
        username = kwargs.get("username") or kwargs.get("user") or kwargs.get("email")

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

