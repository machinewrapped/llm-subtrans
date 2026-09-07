class FakeClock:
    """Advance simulated monotonic time when a test sleeps."""

    def __init__(self) -> None:
        self.seconds : float = 0.0

    def Monotonic(self) -> float:
        return self.seconds

    def Sleep(self, seconds : float) -> None:
        self.seconds += seconds
