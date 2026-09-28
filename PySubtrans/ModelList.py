from collections.abc import Callable
from enum import Enum, auto
from threading import RLock


class ModelListState(Enum):
    """The lifecycle of a provider's model list."""
    Unloaded = auto()   # No lookup has been attempted
    Loading = auto()    # An asynchronous lookup is in progress
    Loaded = auto()     # The list is authoritative, even if it is empty
    Failed = auto()     # The last lookup failed and may be retried


class ModelList:
    """
    The model list for a translation provider, modelled as a state machine.

    Holds the known models and tracks the lifecycle of a lookup.
    A failed lookup is recorded as state rather than raised to callers.
    Each lookup is identified by a request token, so a superseded lookup cannot
    record its result over a newer one.
    """
    def __init__(self, fetch : Callable[[], list[str]]):
        self._fetch = fetch
        self._models : list[str] = []
        self._state : ModelListState = ModelListState.Unloaded
        self._error : str|None = None
        self._request : int = 0
        self._lock = RLock()

    @property
    def state(self) -> ModelListState:
        """
        The current lifecycle state
        """
        return self._state

    @property
    def models(self) -> list[str]:
        """
        The known models, resolving them when there is no resolved or in-progress list
        """
        if self._state in (ModelListState.Unloaded, ModelListState.Failed):
            self.Resolve()

        return self._models

    @property
    def known(self) -> list[str]:
        """
        The known models, never triggering a lookup
        """
        return self._models

    @property
    def resolved(self) -> bool:
        """
        Whether the list is authoritative, even if it is empty
        """
        return self._state == ModelListState.Loaded

    @property
    def pending(self) -> bool:
        """
        Whether an asynchronous lookup is in progress
        """
        return self._state == ModelListState.Loading

    @property
    def error(self) -> str|None:
        """
        The error from the last failed lookup
        """
        return self._error

    def BeginLoad(self) -> int:
        """
        Mark an asynchronous lookup as in progress

        Returns a request token identifying this lookup.
        A later lookup, or a cancel, makes the token stale.
        """
        with self._lock:
            self._state = ModelListState.Loading
            self._request += 1
            return self._request

    def Resolve(self, request : int|None = None) -> bool:
        """
        Run the lookup and record the outcome as state. Never raises.

        The request token from BeginLoad identifies the lookup that produced the
        result, and a stale token is discarded so a superseded lookup cannot
        overwrite a newer result.
        Without a token the outcome is always recorded.
        Returns whether the outcome was recorded.
        """
        try:
            models = list(self._fetch())
            error = None
        except Exception as failure:
            models = []
            error = str(failure)

        with self._lock:
            if request is not None and request != self._request:
                return False

            if error is not None:
                self._error = error
                self._state = ModelListState.Failed
            else:
                self._models = models
                self._error = None
                self._state = ModelListState.Loaded

            return True

    def Cancel(self) -> None:
        """
        Abandon an in-progress lookup so it can be retried

        The abandoned lookup's result is discarded.
        """
        with self._lock:
            if self._state == ModelListState.Loading:
                self._state = ModelListState.Unloaded
            self._request += 1

    def Reset(self) -> None:
        """
        Discard the known models and any lifecycle state

        Also discards the result of any lookup already in progress.
        """
        with self._lock:
            self._models = []
            self._state = ModelListState.Unloaded
            self._error = None
            self._request += 1
