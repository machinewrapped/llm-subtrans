from __future__ import annotations

import base64
import copy
import json
import threading
import time
from typing import Any
import unittest
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import urlopen

from PySubtrans.Helpers.TestCases import LoggedTestCase
from PySubtrans.Helpers.Tests import log_input_expected_error, skip_if_debugger_attached
from PySubtrans.Auth.ChatGPTAuth import (
    DYNAMIC_CLIENT_ID,
    PLAN_USAGE_SCOPE,
    SCOPES,
    TOKEN_URL,
    ChatGPTAuth,
    ChatGPTAuthError,
    ChatGPTCredentialStore,
    CreateCodeChallenge,
    ParseModelList,
)

ISSUED_CLIENT_ID = 'oaiapp_test'
REDIRECT_URI = 'http://127.0.0.1:1455/auth/callback'


class MemoryCredentialStore(ChatGPTCredentialStore):
    """Keeps the sign-in data in memory, so tests never touch the config directory."""
    def __init__(self, data : dict[str, Any]|None = None):
        super().__init__(path='memory')
        self.data : dict[str, Any] = copy.deepcopy(data or {})

    def Load(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    def Save(self, data : dict[str, Any]) -> None:
        self.data = copy.deepcopy(data)


class FakeChatGPTAuth(ChatGPTAuth):
    """Records requests and returns queued responses instead of calling OpenAI."""
    def __init__(self, store : MemoryCredentialStore, responses : list[dict[str, Any]|Exception]|None = None):
        super().__init__(store=store)
        self.responses : list[dict[str, Any]|Exception] = list(responses or [])
        self.requests : list[tuple[str, dict[str, str]]] = []

    def _post_form(self, url : str, form : dict[str, str], expect_json : bool = True) -> dict[str, Any]:
        self.requests.append((url, form))
        return self._next_response()

    def _get_json(self, url : str, access_token : str|None = None) -> dict[str, Any]:
        self.requests.append((url, {'access_token': access_token or ''}))
        return self._next_response()

    def _next_response(self) -> dict[str, Any]:
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def MakeIdToken(claims : dict[str, Any]) -> str:
    """Build an unsigned JWT carrying the given claims."""
    def encode(data : dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode('utf-8')).rstrip(b'=').decode('ascii')
    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


def MakeTokenResponse(nonce : str, client_id : str = ISSUED_CLIENT_ID, scope : str = SCOPES) -> dict[str, Any]:
    return {
        'access_token': 'access-1',
        'refresh_token': 'refresh-1',
        'id_token': MakeIdToken({'aud': client_id, 'nonce': nonce, 'exp': time.time() + 3600, 'email': 'user@example.com'}),
        'expires_in': 3600,
        'scope': scope,
        'token_type': 'Bearer',
    }


def SignedInStore(expires_in : float = 3600.0) -> MemoryCredentialStore:
    return MemoryCredentialStore({
        'host_id': 'urn:uuid:test',
        'client_id': ISSUED_CLIENT_ID,
        'credentials': {
            'access_token': 'access-1',
            'refresh_token': 'refresh-1',
            'id_token': 'id-token',
            'expires_at': time.time() + expires_in,
            'scope': SCOPES,
            'email': 'user@example.com',
        }
    })


class ChatGPTSignInTests(LoggedTestCase):
    """Tests for building the authorization request and handling the callback."""

    def test_first_sign_in_registers_dynamic_client(self) -> None:
        """A first sign-in asks for dynamic registration with PKCE and a persisted host id."""
        store = MemoryCredentialStore()
        auth = FakeChatGPTAuth(store)

        pending = auth.BeginSignIn(REDIRECT_URI)
        params = { key: values[0] for key, values in parse_qs(urlparse(pending.url).query).items() }

        self.assertLoggedEqual('client id', DYNAMIC_CLIENT_ID, params.get('client_id'))
        self.assertLoggedIn('agent name hint', 'agent_name_hint', params)
        self.assertLoggedEqual('code challenge', CreateCodeChallenge(pending.code_verifier), params.get('code_challenge'))
        self.assertLoggedEqual('code challenge method', 'S256', params.get('code_challenge_method'))
        self.assertLoggedEqual('host id', store.data.get('host_id'), params.get('ext_agent_host_id'))
        self.assertLoggedIn('plan usage scope', PLAN_USAGE_SCOPE, (params.get('scope') or '').split())

        second = auth.BeginSignIn(REDIRECT_URI)
        second_params = parse_qs(urlparse(second.url).query)
        self.assertLoggedEqual('host id is reused', params.get('ext_agent_host_id'), second_params['ext_agent_host_id'][0])
        self.assertLoggedFalse('state is fresh', second.state == pending.state)

    def test_reauthorization_reuses_issued_client(self) -> None:
        """A later sign-in reuses the issued client id and does not register again."""
        auth = FakeChatGPTAuth(SignedInStore())

        pending = auth.BeginSignIn(REDIRECT_URI)
        params = parse_qs(urlparse(pending.url).query)

        self.assertLoggedEqual('client id', ISSUED_CLIENT_ID, params['client_id'][0])
        self.assertLoggedNotIn('agent name hint', 'agent_name_hint', params)

    def test_complete_sign_in_stores_credentials(self) -> None:
        """A valid callback exchanges the code and stores the tokens and issued client id."""
        store = MemoryCredentialStore()
        auth = FakeChatGPTAuth(store)
        pending = auth.BeginSignIn(REDIRECT_URI)
        auth.responses.append(MakeTokenResponse(pending.nonce))

        credentials = auth.CompleteSignIn(pending, {'state': pending.state, 'code': 'code-1', 'client_id': ISSUED_CLIENT_ID})

        url, form = auth.requests[0]
        self.assertLoggedEqual('token endpoint', TOKEN_URL, url)
        self.assertLoggedEqual('exchange client id', ISSUED_CLIENT_ID, form.get('client_id'))
        self.assertLoggedEqual('code verifier', pending.code_verifier, form.get('code_verifier'))
        self.assertLoggedEqual('redirect uri', REDIRECT_URI, form.get('redirect_uri'))
        self.assertLoggedEqual('stored client id', ISSUED_CLIENT_ID, store.data.get('client_id'))
        self.assertLoggedTrue('signed in', auth.is_signed_in)
        self.assertLoggedEqual('account', 'user@example.com', auth.account)
        self.assertLoggedEqual('access token', 'access-1', credentials.access_token)

    @skip_if_debugger_attached
    def test_complete_sign_in_rejects_invalid_callbacks(self) -> None:
        """Callbacks that do not match the attempt are rejected without exchanging the code."""
        auth = FakeChatGPTAuth(SignedInStore())
        pending = auth.BeginSignIn(REDIRECT_URI)

        invalid_callbacks = [
            {'state': 'wrong', 'code': 'code-1'},
            {'state': pending.state, 'error': 'access_denied'},
            {'state': pending.state},
            {'state': pending.state, 'code': 'code-1', 'client_id': 'oaiapp_other'},
        ]

        for callback in invalid_callbacks:
            with self.subTest(callback=callback):
                with self.assertRaises(ChatGPTAuthError) as context:
                    auth.CompleteSignIn(pending, callback)
                log_input_expected_error(callback, ChatGPTAuthError, context.exception)

        self.assertLoggedEqual('token requests', 0, len(auth.requests))

    @skip_if_debugger_attached
    def test_complete_sign_in_rejects_invalid_tokens(self) -> None:
        """Tokens for another attempt or client, or without plan usage, are not stored."""
        cases = {
            'nonce mismatch': lambda nonce: MakeTokenResponse('other-nonce'),
            'audience mismatch': lambda nonce: MakeTokenResponse(nonce, client_id='oaiapp_other'),
            'plan usage not granted': lambda nonce: MakeTokenResponse(nonce, scope='openid profile email offline_access'),
        }

        for name, make_response in cases.items():
            with self.subTest(case=name):
                store = MemoryCredentialStore()
                auth = FakeChatGPTAuth(store)
                pending = auth.BeginSignIn(REDIRECT_URI)
                auth.responses.append(make_response(pending.nonce))

                with self.assertRaises(ChatGPTAuthError) as context:
                    auth.CompleteSignIn(pending, {'state': pending.state, 'code': 'code-1', 'client_id': ISSUED_CLIENT_ID})
                log_input_expected_error(name, ChatGPTAuthError, context.exception)

                self.assertLoggedFalse('signed in', auth.is_signed_in)

    def test_sign_in_through_loopback_listener(self) -> None:
        """The browser redirect to the loopback listener completes the sign-in."""
        auth = FakeChatGPTAuth(MemoryCredentialStore())

        def open_browser(url : str) -> bool:
            # Simulate the browser following the redirect after the user signs in
            params = parse_qs(urlparse(url).query)
            redirect_uri = params['redirect_uri'][0]
            state = params['state'][0]
            auth.responses.append(MakeTokenResponse(params['nonce'][0]))

            def redirect() -> None:
                with urlopen(f"{redirect_uri}?{urlencode({'state': state, 'code': 'code-1', 'client_id': ISSUED_CLIENT_ID})}", timeout=10) as response:
                    response.read()

            threading.Thread(target=redirect, daemon=True).start()
            return True

        credentials = auth.SignIn(open_browser=open_browser, timeout=10.0)

        self.assertLoggedEqual('access token', 'access-1', credentials.access_token)
        self.assertLoggedTrue('signed in', auth.is_signed_in)

    @skip_if_debugger_attached
    def test_sign_in_can_be_cancelled(self) -> None:
        """Setting the cancel event stops waiting for the redirect."""
        auth = FakeChatGPTAuth(MemoryCredentialStore())
        cancel_event = threading.Event()
        cancel_event.set()

        with self.assertRaises(ChatGPTAuthError) as context:
            auth.SignIn(cancel_event=cancel_event, open_browser=lambda url: True)
        log_input_expected_error('cancelled', ChatGPTAuthError, context.exception)


class ChatGPTSessionTests(LoggedTestCase):
    """Tests for access token refresh and sign-out."""

    def test_valid_token_is_not_refreshed(self) -> None:
        auth = FakeChatGPTAuth(SignedInStore(expires_in=3600.0))

        self.assertLoggedEqual('access token', 'access-1', auth.GetAccessToken())
        self.assertLoggedEqual('token requests', 0, len(auth.requests))

    def test_expiring_token_is_refreshed_and_rotated(self) -> None:
        """A token close to expiry is refreshed and the replacement refresh token is stored."""
        store = SignedInStore(expires_in=60.0)
        auth = FakeChatGPTAuth(store, responses=[{'access_token': 'access-2', 'refresh_token': 'refresh-2', 'expires_in': 3600}])

        token = auth.GetAccessToken()

        _url, form = auth.requests[0]
        self.assertLoggedEqual('grant type', 'refresh_token', form.get('grant_type'))
        self.assertLoggedEqual('refresh client id', ISSUED_CLIENT_ID, form.get('client_id'))
        self.assertLoggedEqual('refreshed access token', 'access-2', token)
        self.assertLoggedEqual('rotated refresh token', 'refresh-2', store.data['credentials']['refresh_token'])

    def test_min_validity_forces_refresh(self) -> None:
        """Asking for more validity than remains refreshes the token."""
        auth = FakeChatGPTAuth(SignedInStore(expires_in=600.0), responses=[{'access_token': 'access-2', 'expires_in': 3600}])

        self.assertLoggedEqual('default margin keeps token', 'access-1', auth.GetAccessToken())
        self.assertLoggedEqual('longer validity refreshes', 'access-2', auth.GetAccessToken(min_validity=1800.0))

    @skip_if_debugger_attached
    def test_invalid_grant_signs_out(self) -> None:
        """A rejected refresh token clears the session so the user signs in again."""
        error = ChatGPTAuthError('invalid grant', error_code='invalid_grant')
        auth = FakeChatGPTAuth(SignedInStore(expires_in=0.0), responses=[error])

        with self.assertRaises(ChatGPTAuthError) as context:
            auth.GetAccessToken()
        log_input_expected_error('invalid_grant', ChatGPTAuthError, context.exception)

        self.assertLoggedFalse('signed in', auth.is_signed_in)

    def test_sign_out_revokes_and_keeps_registration(self) -> None:
        store = SignedInStore()
        auth = FakeChatGPTAuth(store, responses=[{'revocation_endpoint': 'https://auth.example/revoke'}, {}])

        revoked = auth.SignOut()

        url, form = auth.requests[1]
        self.assertLoggedTrue('revocation confirmed', revoked)
        self.assertLoggedEqual('revocation endpoint', 'https://auth.example/revoke', url)
        self.assertLoggedEqual('revoked token', 'refresh-1', form.get('token'))
        self.assertLoggedFalse('signed in', auth.is_signed_in)
        self.assertLoggedEqual('client id kept', ISSUED_CLIENT_ID, store.data.get('client_id'))

    def test_sign_out_clears_tokens_when_revocation_fails(self) -> None:
        auth = FakeChatGPTAuth(SignedInStore(), responses=[ChatGPTAuthError('unreachable')])

        with self.assertLogs(level='WARNING'):
            revoked = auth.SignOut()

        self.assertLoggedFalse('revocation confirmed', revoked)
        self.assertLoggedFalse('signed in', auth.is_signed_in)


class ChatGPTModelListTests(LoggedTestCase):
    def test_parse_model_list_keeps_listed_models(self) -> None:
        response = {'models': [
            {'slug': 'gpt-b', 'display_name': 'GPT B', 'visibility': 'list'},
            {'slug': 'gpt-hidden', 'display_name': 'Hidden', 'visibility': 'hide'},
            {'slug': 'gpt-a', 'display_name': 'GPT A', 'visibility': 'list'},
            {'display_name': 'No slug'},
        ]}

        self.assertLoggedSequenceEqual('models', ['gpt-a', 'gpt-b'], ParseModelList(response))

    def test_parse_model_list_without_models(self) -> None:
        self.assertLoggedSequenceEqual('models', [], ParseModelList({'data': []}))


if __name__ == '__main__':
    unittest.main()
