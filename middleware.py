"""
Security middleware for Vigil — Document Analyst.
Adds security headers, cache controls, optional auth checks, and CORS behavior.
"""

import os
import secrets

from aiohttp import web

ALLOWED_ORIGINS = os.getenv("VIGIL_ALLOWED_ORIGINS", "").split(",") if os.getenv("VIGIL_ALLOWED_ORIGINS") else []
API_KEY = os.getenv("VIGIL_API_KEY", "")
REQUIRE_PLATFORM_AUTH = os.getenv("VIGIL_REQUIRE_PLATFORM_AUTH", "").strip().lower() in {"1", "true", "yes", "on"}
PLATFORM_AUTH_HEADERS = (
    "X-MS-CLIENT-PRINCIPAL",
    "X-MS-CLIENT-PRINCIPAL-NAME",
    "X-Authenticated-User",
    "X-Forwarded-User",
)


def _is_allowed_origin(origin: str) -> bool:
    return bool(ALLOWED_ORIGINS and origin in ALLOWED_ORIGINS)


def _is_secure_request(request: web.Request) -> bool:
    return request.secure or request.headers.get("X-Forwarded-Proto", "").lower() == "https"


def _has_platform_identity(request: web.Request) -> bool:
    return any(request.headers.get(header, "").strip() for header in PLATFORM_AUTH_HEADERS)


def _has_api_key(request: web.Request) -> bool:
    if not API_KEY:
        return False

    direct_key = request.headers.get("X-Vigil-Api-Key", "")
    if direct_key and secrets.compare_digest(direct_key, API_KEY):
        return True

    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        return secrets.compare_digest(authorization[7:].strip(), API_KEY)

    return False


def _apply_security_headers(request: web.Request, response: web.StreamResponse) -> web.StreamResponse:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.jsdelivr.net; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )

    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"

    if _is_secure_request(request):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"

    origin = request.headers.get("Origin", "")
    if _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-Vigil-Api-Key"
        response.headers["Access-Control-Max-Age"] = "86400"
        response.headers["Vary"] = "Origin"

    return response


@web.middleware
async def security_headers_middleware(request: web.Request, handler):
    """Apply security controls and optional auth checks to every request."""
    if request.path.startswith("/api/") and request.method != "OPTIONS":
        if (REQUIRE_PLATFORM_AUTH or API_KEY) and not (_has_platform_identity(request) or _has_api_key(request)):
            response = web.json_response({"error": "Authentication required"}, status=401)
            return _apply_security_headers(request, response)

    response = await handler(request)
    return _apply_security_headers(request, response)


async def handle_cors_preflight(request: web.Request) -> web.Response:
    """Handle CORS preflight OPTIONS requests."""
    response = web.Response(status=204)
    return _apply_security_headers(request, response)
