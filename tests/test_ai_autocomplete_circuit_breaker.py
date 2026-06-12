"""Circuit breaker for AI inline autocomplete."""

from src.services.ai_autocomplete_circuit_breaker import (
    AiAutocompleteCircuitBreaker,
    get_ai_autocomplete_circuit_breaker,
    reset_ai_autocomplete_circuit_breaker,
)


class TestAiAutocompleteCircuitBreaker:
    def test_opens_after_threshold(self):
        cb = AiAutocompleteCircuitBreaker(failure_threshold=3)
        cb.record_failure("a")
        cb.record_failure("b")
        assert cb.allows_requests()
        cb.record_failure("c")
        assert not cb.allows_requests()
        assert cb.is_open

    def test_stays_open_after_success(self):
        cb = AiAutocompleteCircuitBreaker(failure_threshold=2)
        cb.record_failure("x")
        cb.record_failure("y")
        cb.record_success()
        assert not cb.allows_requests()

    def test_reset_closes_circuit(self):
        cb = AiAutocompleteCircuitBreaker(failure_threshold=1)
        cb.record_failure("err")
        assert not cb.allows_requests()
        cb.reset()
        assert cb.allows_requests()
        assert cb.consecutive_failures == 0

    def test_global_reset_helper(self):
        cb = get_ai_autocomplete_circuit_breaker()
        cb.record_failure("e1")
        cb.record_failure("e2")
        cb.record_failure("e3")
        assert not cb.allows_requests()
        reset_ai_autocomplete_circuit_breaker()
        assert cb.allows_requests()
