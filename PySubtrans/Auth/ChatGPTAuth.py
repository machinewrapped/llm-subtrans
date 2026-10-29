"""
Sign in with ChatGPT, so OpenAI requests can use the user's ChatGPT plan instead of an API key.
See https://developers.openai.com/siwc/token-sharing-open-source for the protocol.

Each application signs in under its own name, set with ConfigureChatGPTApp, and keeps its own tokens.
"""
import base64
from collections.abc import Callable
from dataclasses import dataclass
import hashlib
import html
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener
import uuid
import webbrowser

import regex

from PySubtrans.Helpers.Localization import _
from PySubtrans.Helpers.Resources import GetConfigDir
from PySubtrans.Options import ConfigActionOption
from PySubtrans.SubtitleError import SubtitleError

AUTHORIZE_URL = "https://auth.openai.com/api/accounts/authorize"
TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
OPENID_CONFIGURATION_URL = "https://auth.openai.com/.well-known/openid-configuration"
API_RESOURCE = "https://api.openai.com/v1"
MODELS_URL = f"{API_RESOURCE}/models"
MANAGE_USAGE_URL = "https://chatgpt.com/settings/usage"

DYNAMIC_CLIENT_ID = "dynamic_agent_client"
CALLBACK_PATH = "/auth/callback"
PLAN_USAGE_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = f"openid profile email offline_access resource.invoke {PLAN_USAGE_SCOPE}"

# By default, refresh this many seconds before the access token expires
REFRESH_MARGIN = 120.0

# Refresh tokens rotate, so refreshes and sign-out are serialised to avoid racing a replaced or revoked token
_refresh_lock = threading.Lock()

# The application signing in and its credential file, set once at startup
_app_name : str|None = None
_credential_filename : str|None = None


def ConfigureChatGPTApp(app_name : str, credential_filename : str|None = None) -> None:
    """
    Set the name the application signs in with ChatGPT under.
    It is shown to the user when they sign in.
    The sign-in data is kept in credential_filename in the config directory, or a file named after the application.
    """
    global _app_name, _credential_filename
    _app_name = app_name.strip() or None
    _credential_filename = credential_filename


def GetChatGPTAppName() -> str|None:
    """The name configured with ConfigureChatGPTApp, or None if the application has not identified itself."""
    return _app_name


def GetCredentialFilename(app_name : str) -> str:
    """
    The default name of the file the application's sign-in data is stored in.
    A digest of the exact name keeps names with the same readable slug, such as "My App" and "My-App", apart.
    """
    slug = regex.sub(r'[^\w]+', '-', app_name.casefold()).strip('-')
    if not slug:
        raise ChatGPTAuthError(_("'{app}' cannot be used as an application name for Sign in with ChatGPT").format(app=app_name))

    digest = hashlib.sha256(app_name.encode('utf-8')).hexdigest()[:8]
    return f"chatgpt-auth-{slug}-{digest}.json"


class ChatGPTAuthError(SubtitleError):
    """Sign-in with ChatGPT failed or the session is no longer valid."""
    def __init__(self, message : str, error : Exception|None = None, error_code : str|None = None):
        super().__init__(message, error)
        self.error_code = error_code


class ChatGPTSignInOption(ConfigActionOption):
    """Settings button that signs in with ChatGPT."""
    label = _("Continue with ChatGPT")


class ChatGPTSignOutOption(ConfigActionOption):
    """Settings button that signs out of ChatGPT."""
    label = _("Sign out")


@dataclass
class ChatGPTCredentials:
    """OAuth tokens for a signed-in ChatGPT account."""
    access_token : str
    refresh_token : str
    id_token : str
    expires_at : float
    scope : str
    email : str|None = None

    def ToDict(self) -> dict[str, Any]:
        return {
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'id_token': self.id_token,
            'expires_at': self.expires_at,
            'scope': self.scope,
            'email': self.email,
        }

    @classmethod
    def FromDict(cls, data : dict[str, Any]) -> 'ChatGPTCredentials':
        return cls(
            access_token=str(data.get('access_token', '')),
            refresh_token=str(data.get('refresh_token', '')),
            id_token=str(data.get('id_token', '')),
            expires_at=float(data.get('expires_at', 0.0)),
            scope=str(data.get('scope', '')),
            email=data.get('email'),
        )


@dataclass
class PendingSignIn:
    """The values for one authorization attempt, needed to validate the callback."""
    url : str
    redirect_uri : str
    state : str
    nonce : str
    code_verifier : str
    client_id : str|None


class ChatGPTCredentialStore:
    """
    Persists the host id, issued client id and tokens in the config directory.
    Tokens are kept out of settings.json so they never end up in project or settings files.
    """
    def __init__(self, path : str):
        self.path = path

    def Load(self) -> dict[str, Any]:
        """Read the stored data, or an empty dict if there is none."""
        if not os.path.exists(self.path):
            return {}

        try:
            with open(self.path, 'r', encoding='utf-8') as file:
                data = json.load(file)
                return data if isinstance(data, dict) else {}

        except (OSError, json.JSONDecodeError) as e:
            logging.warning(_("Unable to read ChatGPT sign-in data: {error}").format(error=str(e)))
            return {}

    def Save(self, data : dict[str, Any]) -> None:
        """Write the data, readable only by the current user where the platform allows it."""
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as file:
            json.dump(data, file, indent=2)


class ChatGPTAuth:
    """
    Signs in with ChatGPT and supplies a valid access token for Responses API requests.
    Only one ChatGPT account is supported per host.
    The application must identify itself, with app_name or ConfigureChatGPTApp.
    By default its tokens are kept in a file of its own in the config directory.
    """
    def __init__(self, app_name : str|None = None, store : ChatGPTCredentialStore|None = None, proxy : str|None = None):
        name = (app_name or '').strip()
        if name:
            filename = GetCredentialFilename(name)
        else:
            # Fall back to the application configured at startup, with its chosen credential file
            name = GetChatGPTAppName()
            if not name:
                raise ChatGPTAuthError(_("The application must identify itself with ConfigureChatGPTApp before signing in with ChatGPT"))
            filename = _credential_filename or GetCredentialFilename(name)

        self.app_name : str = name
        self.store = store or ChatGPTCredentialStore(os.path.join(GetConfigDir(), filename))
        self.proxy = proxy

    @property
    def credentials(self) -> ChatGPTCredentials|None:
        data = self.store.Load().get('credentials')
        return ChatGPTCredentials.FromDict(data) if isinstance(data, dict) else None

    @property
    def is_signed_in(self) -> bool:
        credentials = self.credentials
        return credentials is not None and bool(credentials.refresh_token)

    @property
    def account(self) -> str|None:
        """The email address of the signed-in account, for display."""
        credentials = self.credentials
        return credentials.email if credentials else None

    @property
    def welcome_shown(self) -> bool:
        return bool(self.store.Load().get('welcome_shown'))

    def MarkWelcomeShown(self) -> None:
        """Record that the first sign-in message has been shown, so it is not shown again."""
        data = self.store.Load()
        data['welcome_shown'] = True
        self.store.Save(data)

    def SignIn(self, cancel_event : threading.Event|None = None, open_browser : Callable[[str], Any]|None = None, timeout : float = 300.0) -> ChatGPTCredentials:
        """
        Run the browser sign-in, waiting for the redirect on a loopback listener.
        Blocks until the user completes sign-in, the attempt is cancelled or it times out.
        """
        open_browser = open_browser or webbrowser.open

        server = _CallbackServer(('127.0.0.1', 0), _CallbackHandler)
        try:
            server.timeout = 0.5
            server.app_name = self.app_name
            redirect_uri = f"http://127.0.0.1:{server.server_port}{CALLBACK_PATH}"

            pending = self.BeginSignIn(redirect_uri)
            if not open_browser(pending.url):
                logging.info(_("Open this address in your browser to sign in with ChatGPT: {url}").format(url=pending.url))

            deadline = time.monotonic() + timeout
            while server.callback_params is None:
                if cancel_event is not None and cancel_event.is_set():
                    raise ChatGPTAuthError(_("Sign-in with ChatGPT was cancelled"))

                if time.monotonic() > deadline:
                    raise ChatGPTAuthError(_("Sign-in with ChatGPT timed out"))

                server.handle_request()

            return self.CompleteSignIn(pending, server.callback_params)

        finally:
            server.server_close()

    def BeginSignIn(self, redirect_uri : str) -> PendingSignIn:
        """Prepare an authorization attempt with fresh state, nonce and PKCE values."""
        data = self.store.Load()

        host_id = data.get('host_id')
        if not host_id:
            host_id = f"urn:uuid:{uuid.uuid4()}"
            data['host_id'] = host_id
            self.store.Save(data)

        client_id = data.get('client_id')
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)

        params = {
            'client_id': client_id or DYNAMIC_CLIENT_ID,
            'ext_agent_host_id': host_id,
            'response_type': 'code',
            'redirect_uri': redirect_uri,
            'scope': SCOPES,
            'resource': API_RESOURCE,
            'state': state,
            'nonce': nonce,
            'code_challenge_method': 'S256',
            'code_challenge': CreateCodeChallenge(code_verifier),
        }

        if client_id:
            # Reauthorization reuses the issued client, hinting at the previous account
            credentials = self.credentials
            if credentials and credentials.id_token:
                params['id_token_hint'] = credentials.id_token
        else:
            params['agent_name_hint'] = self.app_name

        url = f"{AUTHORIZE_URL}?{urlencode(params)}"
        return PendingSignIn(url=url, redirect_uri=redirect_uri, state=state, nonce=nonce, code_verifier=code_verifier, client_id=client_id)

    def CompleteSignIn(self, pending : PendingSignIn, params : dict[str, str]) -> ChatGPTCredentials:
        """Validate the authorization callback, exchange the code and store the tokens."""
        if params.get('state') != pending.state:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: the response did not match the request"))

        error = params.get('error')
        if error:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: {error}").format(error=params.get('error_description') or error))

        code = params.get('code')
        if not code:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: no authorization code was returned"))

        issued_client_id = params.get('client_id')
        if pending.client_id and issued_client_id and issued_client_id != pending.client_id:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: the response was for a different client"))

        client_id = pending.client_id or issued_client_id
        if not client_id:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: no client id was issued"))

        # Keep the registration even if the exchange fails, so the next attempt reuses it
        data = self.store.Load()
        data['client_id'] = client_id
        self.store.Save(data)

        response = self._post_form(TOKEN_URL, {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'code': code,
            'code_verifier': pending.code_verifier,
            'redirect_uri': pending.redirect_uri,
            'resource': API_RESOURCE,
        })

        id_token = str(response.get('id_token') or '')
        claims = DecodeJwtClaims(id_token)
        self._validate_id_token(claims, client_id, pending.nonce)

        scope = str(response.get('scope') or params.get('scope') or '')
        if PLAN_USAGE_SCOPE not in scope.split():
            raise ChatGPTAuthError(_("ChatGPT plan usage was not granted for this account"))

        credentials = self._credentials_from_response(response, id_token=id_token, scope=scope, email=claims.get('email'))
        self._save_credentials(credentials)
        return credentials

    def GetAccessToken(self, min_validity : float = REFRESH_MARGIN) -> str:
        """Return an access token valid for at least min_validity seconds, refreshing it if necessary."""
        with _refresh_lock:
            # Reload in case another process has already rotated the tokens
            credentials = self.credentials
            if not credentials or not credentials.refresh_token:
                raise ChatGPTAuthError(_("Not signed in with ChatGPT"))

            if credentials.expires_at - min_validity > time.time():
                return credentials.access_token

            return self._refresh(credentials).access_token

    def SignOut(self) -> bool:
        """
        Revoke the refresh token and forget the stored tokens.
        The client registration is kept for the next sign-in.
        Returns False if remote revocation could not be confirmed.
        """
        # Hold the refresh lock throughout, so a refresh in progress cannot restore the tokens afterwards
        with _refresh_lock:
            data = self.store.Load()
            credentials = self.credentials
            client_id = data.get('client_id')

            revoked = True
            if credentials and credentials.refresh_token and client_id:
                try:
                    configuration = self._get_json(OPENID_CONFIGURATION_URL)
                    revocation_url = str(configuration.get('revocation_endpoint') or '')
                    if not revocation_url:
                        raise ChatGPTAuthError(_("No revocation endpoint is published"))

                    self._post_form(revocation_url, {
                        'token': credentials.refresh_token,
                        'token_type_hint': 'refresh_token',
                        'client_id': client_id,
                    }, expect_json=False)

                except ChatGPTAuthError as e:
                    logging.warning(_("Unable to confirm ChatGPT sign-out: {error}").format(error=str(e)))
                    revoked = False

            data.pop('credentials', None)
            self.store.Save(data)
            return revoked

    def ListModels(self) -> list[str]:
        """Return the models available to the signed-in account."""
        response = self._get_json(MODELS_URL, access_token=self.GetAccessToken())
        return ParseModelList(response)

    def _refresh(self, credentials : ChatGPTCredentials) -> ChatGPTCredentials:
        """Exchange the refresh token for new tokens. Must be called with the refresh lock held."""
        client_id = self.store.Load().get('client_id')
        if not client_id:
            raise ChatGPTAuthError(_("Not signed in with ChatGPT"))

        try:
            response = self._post_form(TOKEN_URL, {
                'grant_type': 'refresh_token',
                'client_id': client_id,
                'refresh_token': credentials.refresh_token,
                'resource': API_RESOURCE,
            })

        except ChatGPTAuthError as e:
            if e.error_code == 'invalid_grant':
                self._clear_credentials()
                raise ChatGPTAuthError(_("Your ChatGPT session has expired. Sign in again to continue.")) from e
            raise

        refreshed = self._credentials_from_response(response,
            id_token=str(response.get('id_token') or credentials.id_token),
            scope=str(response.get('scope') or credentials.scope),
            email=credentials.email,
            refresh_token=credentials.refresh_token)

        self._save_credentials(refreshed)
        return refreshed

    def _credentials_from_response(self, response : dict[str, Any], id_token : str, scope : str, email : Any, refresh_token : str|None = None) -> ChatGPTCredentials:
        """Build credentials from a token response, keeping the old refresh token if no replacement was issued."""
        access_token = str(response.get('access_token') or '')
        if not access_token:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: no access token was returned"))

        new_refresh_token = str(response.get('refresh_token') or refresh_token or '')
        if not new_refresh_token:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: no refresh token was returned"))

        expires_in = float(response.get('expires_in') or 3600)

        return ChatGPTCredentials(
            access_token=access_token,
            refresh_token=new_refresh_token,
            id_token=id_token,
            expires_at=time.time() + expires_in,
            scope=scope,
            email=str(email) if email else None,
        )

    def _validate_id_token(self, claims : dict[str, Any], client_id : str, nonce : str) -> None:
        """
        Check the ID token was issued for this client and attempt.
        The signature is not checked because the token came directly from the token endpoint over TLS.
        """
        audience = claims.get('aud')
        audiences = audience if isinstance(audience, list) else [audience]
        if client_id not in audiences:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: the ID token was issued for a different client"))

        if claims.get('nonce') != nonce:
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: the ID token did not match the request"))

        expiry = claims.get('exp')
        if isinstance(expiry, (int, float)) and expiry < time.time():
            raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: the ID token has expired"))

    def _save_credentials(self, credentials : ChatGPTCredentials) -> None:
        data = self.store.Load()
        data['credentials'] = credentials.ToDict()
        self.store.Save(data)

    def _clear_credentials(self) -> None:
        data = self.store.Load()
        data.pop('credentials', None)
        self.store.Save(data)

    def _post_form(self, url : str, form : dict[str, str], expect_json : bool = True) -> dict[str, Any]:
        """POST a form-encoded request and return the JSON response."""
        request = Request(url, data=urlencode(form).encode('utf-8'), method='POST', headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
        })
        return self._send(request, expect_json)

    def _get_json(self, url : str, access_token : str|None = None) -> dict[str, Any]:
        """GET a JSON resource, optionally with a bearer token."""
        headers = {'Accept': 'application/json'}
        if access_token:
            headers['Authorization'] = f"Bearer {access_token}"

        return self._send(Request(url, method='GET', headers=headers), expect_json=True)

    def _send(self, request : Request, expect_json : bool) -> dict[str, Any]:
        try:
            with self._opener().open(request, timeout=30) as response:
                body = response.read()

        except HTTPError as e:
            error_code, message = _parse_error_body(e.read())
            raise ChatGPTAuthError(_("ChatGPT request failed ({status}): {error}").format(
                status=e.code, error=message or e.reason), error_code=error_code) from e

        except URLError as e:
            raise ChatGPTAuthError(_("Unable to reach ChatGPT: {error}").format(error=str(e.reason))) from e

        if not expect_json or not body:
            return {}

        try:
            result = json.loads(body)
        except json.JSONDecodeError as e:
            raise ChatGPTAuthError(_("Invalid response from ChatGPT")) from e

        return result if isinstance(result, dict) else {}

    def _opener(self) -> OpenerDirector:
        if self.proxy:
            return build_opener(ProxyHandler({'http': self.proxy, 'https': self.proxy}))
        return build_opener()


def CreateCodeChallenge(code_verifier : str) -> str:
    """The PKCE S256 challenge: base64url SHA-256 of the verifier, without padding."""
    digest = hashlib.sha256(code_verifier.encode('ascii')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('ascii')


def DecodeJwtClaims(token : str) -> dict[str, Any]:
    """Decode the payload of a JWT without verifying its signature."""
    parts = token.split('.')
    if len(parts) != 3:
        raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: invalid ID token"))

    payload = parts[1] + '=' * (-len(parts[1]) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload))
    except (ValueError, json.JSONDecodeError) as e:
        raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: invalid ID token")) from e

    if not isinstance(claims, dict):
        raise ChatGPTAuthError(_("Sign-in with ChatGPT failed: invalid ID token"))

    return claims


def ParseModelList(response : dict[str, Any]) -> list[str]:
    """Extract the model ids the account can select from a ChatGPT plan model listing."""
    models = response.get('models')
    if not isinstance(models, list):
        return []

    return sorted(str(model['slug']) for model in models
                  if isinstance(model, dict) and model.get('slug') and model.get('visibility', 'list') == 'list')


def _parse_error_body(body : bytes) -> tuple[str|None, str|None]:
    """Extract the OAuth or API error code and message from an error response."""
    try:
        data = json.loads(body)
    except (ValueError, json.JSONDecodeError):
        return None, None

    if not isinstance(data, dict):
        return None, None

    error = data.get('error')
    if isinstance(error, dict):
        return error.get('code') or error.get('type'), error.get('message')

    return (str(error) if error else None), data.get('error_description')


class _CallbackServer(HTTPServer):
    """Loopback listener that captures the authorization redirect."""
    callback_params : dict[str, str]|None = None
    app_name : str = ''


class _CallbackHandler(BaseHTTPRequestHandler):
    """Records the query parameters of the authorization redirect."""
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_error(404)
            return

        server = cast(_CallbackServer, self.server)
        server.callback_params = { key: values[0] for key, values in parse_qs(parsed.query).items() if values }

        message = _("Sign-in complete. You can close this window and return to {app}.").format(app=html.escape(server.app_name))
        content = f"<html><body><p>{message}</p></body></html>".encode('utf-8')

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format : str, *args : Any) -> None:
        # The request line includes the authorization code, so it is never logged
        return
