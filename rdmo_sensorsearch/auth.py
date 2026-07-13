import logging
from contextvars import ContextVar
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)

_CURRENT_REQUEST: ContextVar[Any | None] = ContextVar("rdmo_sensorsearch_current_request", default=None)


class SensorSearchAuthContextMiddleware:
    """
    Stores the current request so signal handlers can reuse the user's token.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _CURRENT_REQUEST.set(request)
        try:
            return self.get_response(request)
        finally:
            _CURRENT_REQUEST.reset(token)


def get_current_request():
    return _CURRENT_REQUEST.get()


def get_sms_auth_token(user=None, request=None) -> str | None:
    request = request or get_current_request()
    user = user or getattr(request, "user", None)

    token = _get_custom_auth_token(user=user, request=request)
    if token:
        return token

    token = _get_session_auth_token(request)
    if token:
        return token

    return _get_social_auth_token(user)


def _get_custom_auth_token(user=None, request=None) -> str | None:
    resolver = getattr(settings, "SENSORS_SEARCH_AUTH_TOKEN_RESOLVER", None)
    if not resolver:
        return None

    if isinstance(resolver, str):
        resolver = import_string(resolver)

    try:
        token = resolver(user=user, request=request)
    except TypeError:
        token = resolver(user)

    return _normalize_token(token)


def _get_session_auth_token(request) -> str | None:
    session = getattr(request, "session", None)
    if not session:
        return None

    configured_keys = getattr(settings, "SENSORS_SEARCH_AUTH_SESSION_TOKEN_KEYS", None)
    if configured_keys:
        for key in configured_keys:
            token = _normalize_token(session.get(key))
            if token:
                return token
        return None

    access_token_keys = [key for key in session.keys() if key == "access_token" or key.endswith(".access_token")]
    if len(access_token_keys) != 1:
        if len(access_token_keys) > 1:
            logger.warning(
                "Skipping SMS auth token reuse because multiple session access tokens are available: %s",
                access_token_keys,
            )
        return None

    return _normalize_token(session.get(access_token_keys[0]))


def _get_social_auth_token(user) -> str | None:
    if user is None or not getattr(user, "is_authenticated", False):
        return None

    try:
        from allauth.socialaccount.models import SocialToken
    except ImportError:
        return None

    provider_ids = getattr(settings, "SENSORS_SEARCH_AUTH_SOCIALACCOUNT_PROVIDERS", None)
    tokens = SocialToken.objects.filter(account__user=user).exclude(token__isnull=True).exclude(token__exact="")

    if provider_ids:
        tokens = tokens.filter(account__provider__in=provider_ids)

    tokens = [token for token in tokens.select_related("account") if _is_social_token_usable(token)]
    if not tokens:
        return None

    if len(tokens) > 1:
        providers = sorted({token.account.provider for token in tokens})
        logger.warning(
            "Skipping SMS auth token reuse because multiple social auth tokens are available. "
            "Configure SENSORS_SEARCH_AUTH_SOCIALACCOUNT_PROVIDERS to select one provider. Providers: %s",
            providers,
        )
        return None

    return _normalize_token(tokens[0].token)


def _is_social_token_usable(token) -> bool:
    expires_at = getattr(token, "expires_at", None)
    return expires_at is None or expires_at > timezone.now()


def _normalize_token(token) -> str | None:
    if not isinstance(token, str):
        return None
    token = token.strip()
    if not token:
        return None
    if token.lower().startswith("bearer "):
        return token[7:].strip() or None
    return token
