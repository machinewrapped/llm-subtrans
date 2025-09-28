import threading

from copy import deepcopy
from datetime import timedelta

from PySubtrans.Helpers.TestCases import SubtitleTestCase, DummyTranslationClient
from PySubtrans.Helpers.Tests import log_test_name, log_input_expected_result, log_info, skip_if_debugger_attached_decorator
from PySubtrans.SettingsType import SettingsType, SettingType
from PySubtrans.SubtitleBatch import SubtitleBatch
from PySubtrans.SubtitleBuilder import SubtitleBuilder
from PySubtrans.SubtitleError import TranslationError
from PySubtrans.SubtitleTranslator import SubtitleTranslator
from PySubtrans.Translation import Translation
from PySubtrans.TranslationClient import TranslationClient
from PySubtrans.TranslationPrompt import TranslationPrompt
from PySubtrans.TranslationProvider import TranslationProvider
from PySubtrans.TranslationRequest import TranslationRequest, StreamingCallback

class MockStreamingTranslationClient(DummyTranslationClient):
    """Mock streaming client for testing streaming functionality"""

    def __init__(self, settings : SettingsType):
        # Ensure streaming support is enabled in settings
        settings.setdefault('supports_streaming', True)
        super().__init__(settings)
        self.streaming_responses : dict[str, list[str]] = settings.get_dict('streaming_responses') #type: ignore
        self.network_error_on_delta : int|None = settings.get_int('network_error_on_delta') if settings.get('network_error_on_delta') is not None else None
        self.api_error_on_delta : int|None = settings.get_int('api_error_on_delta') if settings.get('api_error_on_delta') is not None else None

    def _request_translation(self, request: TranslationRequest, temperature: float|None = None) -> Translation|None:
        # Check if we have streaming response for this prompt
        if request.prompt.user_prompt in self.streaming_responses:
            deltas = self.streaming_responses[request.prompt.user_prompt]
            return self._simulate_streaming(request, deltas)

        # Fall back to non-streaming response
        return super()._request_translation(request, temperature)

    def _simulate_streaming(self, request: TranslationRequest, deltas: list[str]) -> Translation|None:
        """Simulate streaming by calling streaming callback with deltas"""
        if not request.streaming_callback:
            # No streaming callback, return complete response
            return Translation({'text': ''.join(deltas)})

        accumulated_text = ""
        for i, delta in enumerate(deltas):
            # Simulate network or API errors at specific delta indices
            if self.network_error_on_delta == i:
                raise ConnectionError("Simulated network interruption")
            if self.api_error_on_delta == i:
                raise TranslationError("Simulated API error")

            accumulated_text += delta

            # Skip artificial delays in unit tests for speed
            # Real streaming clients will have natural network delays

            # Call streaming callback with delta
            request.ProcessStreamingDelta(delta)

        # Return final complete response
        return Translation({'text': accumulated_text})


class MockStreamingProvider(TranslationProvider):
    """Mock provider that supports streaming"""

    name = "Mock Streaming Provider"

    def __init__(self, data : dict[str,SettingType], streaming_responses : dict[str, list[str]]|None = None):
        settings = SettingsType({
            "model": "mock-streaming",
            "data": data,
            "streaming_responses": streaming_responses or {},
            "supports_streaming": True,
            "stream_responses": True
        }) #type: ignore
        super().__init__("Mock Streaming Provider", settings)

    def GetTranslationClient(self, settings : SettingsType) -> TranslationClient:
        client_settings : dict = deepcopy(self.settings)
        client_settings.update(settings)
        return MockStreamingTranslationClient(settings=client_settings)


class StreamingTests(SubtitleTestCase):
    """Test suite for streaming functionality"""

    def __init__(self, methodName):
        super().__init__(methodName, custom_options={
            'max_batch_size': 10,
            'stream_responses': True
        })

    def test_streaming_event_handling(self):
        """Test that streaming events are properly emitted and handled"""
        log_test_name("Streaming event handling tests")

        # Build controlled test subtitles using SubtitleBuilder
        subtitles = (SubtitleBuilder(max_batch_size=10)
            .AddScene(summary="Test scene for streaming")
            .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "First line")
            .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Second line")
            .BuildLine(timedelta(seconds=7), timedelta(seconds=9), "Third line")
            .Build())

        # Create streaming response that will be split into 3 chunks
        complete_response = "#1\nOriginal>\nFirst line\nTranslation>\nFirst translation\n\n#2\nOriginal>\nSecond line\nTranslation>\nSecond translation\n\n#3\nOriginal>\nThird line\nTranslation>\nThird translation\n\n"

        # Add metadata required by DummyTranslationClient
        test_data = {
            'movie_name': 'Test Movie',
            'description': 'Test streaming functionality',
            'names': ['TestChar1', 'TestChar2'],
            'response_map': {
                "Translate scene 1 batch 1": complete_response
            }
        }

        subtitles.UpdateSettings(SettingsType(test_data))

        # Programmatically chunk complete_response - each line group becomes its own chunk
        chunks = complete_response.split('\n\n')
        streaming_chunks = [chunk + "\n\n" for chunk in chunks if chunk.strip()]

        streaming_responses = {
            "Translate scene 1 batch 1": streaming_chunks
        }

        provider = MockStreamingProvider(test_data, streaming_responses)
        translator = SubtitleTranslator(self.options, translation_provider=provider)

        # Connect test-specific handlers to suppress warning/error noise
        def on_test_error(sender, message):
            log_info(f"Test error event: {message}")

        def on_test_warning(sender, message):
            log_info(f"Test warning event: {message}")

        translator.events.error.connect(on_test_error)
        translator.events.warning.connect(on_test_warning)

        # Track events
        batch_updated_events = []
        batch_translated_events = []

        def on_batch_updated(sender, **kwargs):
            batch_updated_events.append(kwargs)
            batch = kwargs.get('batch')
            batch_num = batch.number if batch else 'unknown'
            log_info(f"batch_updated event: batch={batch_num}")

        def on_batch_translated(sender, **kwargs):
            batch_translated_events.append(kwargs)
            batch = kwargs.get('batch')
            batch_num = batch.number if batch else 'unknown'
            log_info(f"batch_translated event: batch={batch_num}")

        translator.events.batch_updated.connect(on_batch_updated)
        translator.events.batch_translated.connect(on_batch_translated)

        # Execute translation
        translator.TranslateSubtitles(subtitles)

        # We know exactly what to expect: 3 streaming chunks = 3 batch_updated, 1 batch_translated
        log_input_expected_result("batch_updated events count", 3, len(batch_updated_events))
        log_input_expected_result("batch_translated events count", 1, len(batch_translated_events))

        self.assertEqual(len(batch_updated_events), 3, "Should have 3 streaming update events (one per chunk)")
        self.assertEqual(len(batch_translated_events), 1, "Should have 1 completion event")

        # Validate event content
        for event in batch_updated_events:
            self.assertIn('batch', event)
            self.assertIsInstance(event['batch'], SubtitleBatch)
            batch = event['batch']
            self.assertIsNotNone(batch.scene)
            assert batch.scene is not None  # PyLance hint
            self.assertEqual(batch.number, 1)  # We know it's batch 1
            self.assertEqual(batch.scene, 1)   # We know it's scene 1

    def test_partial_response_processing(self):
        """Test that partial responses are processed correctly"""
        log_test_name("Partial response processing tests")

        # Create a mock translation request
        prompt = TranslationPrompt("Test prompt", True)
        request = TranslationRequest(prompt)

        # Test data with multiple line groups
        partial_deltas = [
            "#1\nOriginal>\nいつものように食事が終わるまでは誰も入れないでくれ.\n",
            "Translation>\nAs usual, don't let anyone in until the meal is over.\n\n",  # Complete line group
            "#2\nOriginal>\nいつものやつを頼む星野だ 親父を頼む星野です.\n",
            "Translation>\nIt's Hoshino, ordering the usual. Hoshino, asking for the boss.\n\n"  # Another complete line group
        ]

        # Track partial updates
        partial_updates = []
        def mock_callback(translation : Translation) -> None:
            partial_updates.append(translation)
            log_info(f"Partial update received: {type(translation).__name__}")

        request.streaming_callback = mock_callback

        # Process deltas sequentially
        for delta in partial_deltas:
            request.ProcessStreamingDelta(delta)

        # Validate partial updates - we sent 4 deltas with 2 complete line groups
        actual_update_count = len(partial_updates)
        log_input_expected_result("Partial updates count", 2, actual_update_count)
        self.assertEqual(actual_update_count, 2, "Should have exactly 2 partial updates for 2 complete line groups")

        # Validate that updates are Translation objects
        for update in partial_updates:
            self.assertIsInstance(update, Translation)

        # Test final accumulated response
        final_response = request.accumulated_text
        contains_first = "As usual, don't let anyone in" in final_response
        contains_second = "Hoshino, ordering the usual" in final_response
        log_input_expected_result("Contains first text", True, contains_first)
        log_input_expected_result("Contains second text", True, contains_second)
        self.assertIn("As usual, don't let anyone in", final_response)
        self.assertIn("Hoshino, ordering the usual", final_response)



    @skip_if_debugger_attached_decorator
    def test_network_interruption_handling(self):
        """Test handling of network interruptions during streaming"""
        log_test_name("Network interruption handling tests")

        # Use controlled data instead of unpredictable chinese_dinner_data
        subtitles = (SubtitleBuilder(max_batch_size=10)
            .AddScene(summary="Test scene for network error")
            .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test line 1")
            .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Test line 2")
            .Build())

        complete_response = "#1\nOriginal>\nTest line 1\nTranslation>\nTranslated line 1\n\n#2\nOriginal>\nTest line 2\nTranslation>\nTranslated line 2\n\n"

        test_data = {
            'movie_name': 'Test Movie',
            'description': 'Test network interruption',
            'names': ['Character1'],
            'response_map': {
                "Translate scene 1 batch 1": complete_response
            }
        }

        subtitles.UpdateSettings(SettingsType(test_data))

        streaming_responses = {
            "Translate scene 1 batch 1": [
                "#1\nOriginal>\nTest line 1\n",
                "Translation>\nTranslated",  # Network error will occur here
                " line 1\n\n#2\nOriginal>\nTest line 2\nTranslation>\nTranslated line 2\n\n"
            ]
        }

        # Configure provider to simulate network error on second delta
        provider = MockStreamingProvider(test_data, streaming_responses)
        provider.settings.add('network_error_on_delta', 1)  # Error on second delta

        translator = SubtitleTranslator(self.options, translation_provider=provider)

        # Connect test-specific handlers to suppress warning/error noise
        def on_test_error(sender, message):
            log_info(f"Test error event: {message}")

        def on_test_warning(sender, message):
            log_info(f"Test warning event: {message}")

        translator.events.error.connect(on_test_error)
        translator.events.warning.connect(on_test_warning)

        # Should handle network error gracefully
        with self.assertRaises(ConnectionError) as context:
            translator.TranslateSubtitles(subtitles)

        error_message = str(context.exception).lower()
        contains_interruption = "network interruption" in error_message
        log_input_expected_result("Network error message contains 'network interruption'", True, contains_interruption)
        self.assertIn("network interruption", error_message)

    @skip_if_debugger_attached_decorator
    def test_api_error_handling(self):
        """Test handling of API errors during streaming"""
        log_test_name("API error handling tests")

        # Use controlled data instead of unpredictable chinese_dinner_data
        subtitles = (SubtitleBuilder(max_batch_size=10)
            .AddScene(summary="Test scene for API error")
            .BuildLine(timedelta(seconds=1), timedelta(seconds=3), "Test line 1")
            .BuildLine(timedelta(seconds=4), timedelta(seconds=6), "Test line 2")
            .Build())

        complete_response = "#1\nOriginal>\nTest line 1\nTranslation>\nTranslated line 1\n\n#2\nOriginal>\nTest line 2\nTranslation>\nTranslated line 2\n\n"

        test_data = {
            'movie_name': 'Test Movie',
            'description': 'Test API error',
            'names': ['Character1'],
            'response_map': {
                "Translate scene 1 batch 1": complete_response
            }
        }

        subtitles.UpdateSettings(SettingsType(test_data))

        streaming_responses = {
            "Translate scene 1 batch 1": [
                "#1\nOriginal>\nTest line 1\n",
                "Translation>\nTranslated",  # API error will occur here
                " line 1\n\n#2\nOriginal>\nTest line 2\nTranslation>\nTranslated line 2\n\n"
            ]
        }

        # Configure provider to simulate API error on second delta
        provider = MockStreamingProvider(test_data, streaming_responses)
        provider.settings.add('api_error_on_delta', 1)  # Error on second delta

        translator = SubtitleTranslator(self.options, translation_provider=provider)

        # Connect test-specific handlers to suppress warning/error noise
        def on_test_error(sender, message):
            log_info(f"Test error event: {message}")

        def on_test_warning(sender, message):
            log_info(f"Test warning event: {message}")

        translator.events.error.connect(on_test_error)
        translator.events.warning.connect(on_test_warning)

        # Should handle API error gracefully without raising exception
        translator.TranslateSubtitles(subtitles)

        # Verify that errors were captured - we simulated exactly 1 API error
        error_count = len(translator.errors)
        log_input_expected_result("Error count", 1, error_count)
        self.assertEqual(error_count, 1)

        # Verify the error message contains our simulated error
        error_messages = [str(error) for error in translator.errors]
        found_api_error = any("API error" in msg for msg in error_messages)
        log_input_expected_result("Contains API error", True, found_api_error)
        self.assertTrue(found_api_error)


    def test_concurrent_streaming_requests(self):
        """Test handling of multiple concurrent streaming requests"""
        log_test_name("Concurrent streaming requests tests")

        # Use controlled data for predictable results
        def create_streaming_translator(thread_id):
            subtitles = (SubtitleBuilder(max_batch_size=10)
                .AddScene(summary=f"Thread {thread_id} scene")
                .BuildLine(timedelta(seconds=1), timedelta(seconds=3), f"Thread {thread_id} line 1")
                .BuildLine(timedelta(seconds=4), timedelta(seconds=6), f"Thread {thread_id} line 2")
                .Build())

            # Each thread gets its own complete response
            complete_response = f"#1\nOriginal>\nThread {thread_id} line 1\nTranslation>\nTranslated thread {thread_id} line 1\n\n#2\nOriginal>\nThread {thread_id} line 2\nTranslation>\nTranslated thread {thread_id} line 2\n\n"

            test_data = {
                'movie_name': f'Test Movie {thread_id}',
                'description': f'Concurrent test thread {thread_id}',
                'names': ['Character1'],
                'response_map': {
                    "Translate scene 1 batch 1": complete_response
                }
            }

            subtitles.UpdateSettings(SettingsType(test_data))

            streaming_responses = {
                "Translate scene 1 batch 1": [
                    f"#1\nOriginal>\nThread {thread_id} line 1\nTranslation>\nTranslated thread {thread_id} line 1\n\n",
                    f"#2\nOriginal>\nThread {thread_id} line 2\nTranslation>\nTranslated thread {thread_id} line 2\n\n"
                ]
            }

            provider = MockStreamingProvider(test_data, streaming_responses)
            translator = SubtitleTranslator(self.options, translation_provider=provider)
            return translator, subtitles

        # Create exactly 3 translators
        num_threads = 3
        translators_and_subtitles = [create_streaming_translator(i) for i in range(num_threads)]

        results = []
        threads = []

        def run_translation(translator, subtitles, index):
            try:
                translator.TranslateSubtitles(subtitles)
                results.append((index, True, None))
            except Exception as e:
                results.append((index, False, str(e)))

        # Start concurrent translations
        for i, (translator, subtitles) in enumerate(translators_and_subtitles):
            thread = threading.Thread(target=run_translation, args=(translator, subtitles, i))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5.0)  # 5 second timeout

        # Validate exactly 3 results as expected
        log_input_expected_result("Concurrent translation results", num_threads, len(results))
        self.assertEqual(len(results), num_threads)

        # Validate all succeeded
        success_count = sum(1 for _, success, _ in results if success)
        log_input_expected_result("Successful translations", num_threads, success_count)
        self.assertEqual(success_count, num_threads, f"All {num_threads} concurrent translations should succeed")

