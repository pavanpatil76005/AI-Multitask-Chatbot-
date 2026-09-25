import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from google.genai import errors
from app.ai.gemini_provider import GeminiProvider, RETRYABLE_CODES
from app.services.ai_service import generate_chat_response, generate_chat_response_stream


def api_error(code):
    return errors.APIError(code, {"error": {"code": code, "message": "PRIVATE_API_DETAIL"}})


def failing_stream(code, prefix=None):
    if prefix is not None:
        yield SimpleNamespace(text=prefix)
    raise api_error(code)


class GeminiTests(unittest.TestCase):
    def setUp(self):
        self.patch = patch("app.ai.gemini_provider.genai.Client")
        self.factory = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.provider = GeminiProvider(api_key="test-key", model="gemini-3.8-flash", fallback_model="gemini-3.6-flash", second_fallback_model="")

    def test_sdk_retry_configuration_and_primary_success(self):
        self.client.models.generate_content.return_value = SimpleNamespace(text=" OK ")
        self.assertEqual(self.provider.generate("hello"), "OK")
        options = self.factory.call_args.kwargs["http_options"].retry_options
        self.assertEqual((options.attempts, options.initial_delay, options.max_delay, options.exp_base), (3, 1, 8, 2))
        self.assertEqual(set(options.http_status_codes), RETRYABLE_CODES)
        config = self.client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.thinking_config.thinking_level.value.lower(), "low")

    def test_fallback_for_each_transient_code(self):
        for code in RETRYABLE_CODES:
            with self.subTest(code=code):
                call = self.client.models.generate_content
                call.reset_mock()
                call.side_effect = [api_error(code), SimpleNamespace(text="Recovered")]
                self.assertEqual(self.provider.generate("test"), "Recovered")
                self.assertEqual([c.kwargs["model"] for c in call.call_args_list], ["gemini-3.8-flash", "gemini-3.6-flash"])

    def test_no_fallback_on_permanent_or_unexpected_errors(self):
        for error in [api_error(c) for c in (400, 401, 403, 404)] + [RuntimeError("503-looking text")]:
            self.client.models.generate_content.reset_mock()
            self.client.models.generate_content.side_effect = error
            with self.assertRaises(type(error)):
                self.provider.generate("test")
            self.assertEqual(self.client.models.generate_content.call_count, 1)

    def test_exhaustion_and_empty_results(self):
        self.client.models.generate_content.side_effect = api_error(503)
        with self.assertRaises(errors.APIError):
            self.provider.generate("test")
        self.client.models.generate_content.side_effect = [SimpleNamespace(text=" "), SimpleNamespace(text="OK")]
        self.assertEqual(self.provider.generate("test"), "OK")
        self.client.models.generate_content.side_effect = None
        self.client.models.generate_content.return_value = SimpleNamespace(text=None)
        with self.assertRaisesRegex(RuntimeError, "empty"):
            self.provider.generate("test")

    def test_stream_lazy_error_falls_back_preserving_whitespace(self):
        self.client.models.generate_content_stream.side_effect = [failing_stream(503), iter([SimpleNamespace(text="Hello "), SimpleNamespace(text=" world\n")])]
        self.assertEqual("".join(self.provider.stream_generate("test")), "Hello  world\n")
        self.assertEqual(self.client.models.generate_content_stream.call_count, 2)

    def test_partial_stream_continues_on_next_model(self):
        self.client.models.generate_content_stream.side_effect = [
            failing_stream(503, "First "), iter([SimpleNamespace(text="second")])]
        self.assertEqual("".join(self.provider.stream_generate("test")), "First second")
        self.assertIn("<existing_answer>First </existing_answer>", self.client.models.generate_content_stream.call_args.kwargs["contents"])

    def test_second_fallback_generate_and_stream(self):
        self.provider.second_fallback_model = "gemini-3.5-flash-lite"
        self.client.models.generate_content.side_effect = [api_error(503), api_error(429), SimpleNamespace(text="third")]
        self.assertEqual(self.provider.generate("test"), "third")
        self.assertEqual(self.client.models.generate_content.call_args.kwargs["model"], "gemini-3.5-flash-lite")
        self.client.models.generate_content_stream.side_effect = [failing_stream(503, "A"), failing_stream(503, " B"), iter([SimpleNamespace(text=" C")])]
        self.assertEqual("".join(self.provider.stream_generate("test")), "A B C")
        self.assertIn("<existing_answer>A B</existing_answer>", self.client.models.generate_content_stream.call_args.kwargs["contents"])

    def test_partial_exhaustion_preserves_output_and_raises(self):
        self.client.models.generate_content_stream.side_effect = [failing_stream(503, "Useful text"), failing_stream(503)]
        stream = self.provider.stream_generate("test")
        self.assertEqual(next(stream), "Useful text")
        with self.assertRaises(errors.APIError):
            next(stream)

    def test_transport_disconnect_continues(self):
        import httpx
        def disconnected():
            yield SimpleNamespace(text="Keep ")
            raise httpx.ReadError("connection lost")
        self.client.models.generate_content_stream.side_effect = [disconnected(), iter([SimpleNamespace(text="going")])]
        self.assertEqual("".join(self.provider.stream_generate("test")), "Keep going")

    def test_nonstream_transport_failure_uses_fallback(self):
        import httpx
        self.client.models.generate_content.side_effect = [httpx.ConnectError("private details"), SimpleNamespace(text="Recovered")]
        self.assertEqual(self.provider.generate("question"), "Recovered")
        self.assertEqual(self.client.models.generate_content.call_count, 2)

    def test_stream_permanent_error_and_empty_stream(self):
        self.client.models.generate_content_stream.return_value = failing_stream(401)
        with self.assertRaises(errors.APIError):
            list(self.provider.stream_generate("test"))
        self.assertEqual(self.client.models.generate_content_stream.call_count, 1)
        self.client.models.generate_content_stream.side_effect = [iter([]), iter([SimpleNamespace(text="fallback")])]
        self.assertEqual(list(self.provider.stream_generate("test")), ["fallback"])

    def test_deduplicate_models(self):
        self.provider.fallback_model = self.provider.model
        self.client.models.generate_content.side_effect = api_error(503)
        with self.assertRaises(errors.APIError):
            self.provider.generate("test")
        self.assertEqual(self.client.models.generate_content.call_count, 1)

    def test_service_logs_code_without_private_error_details(self):
        messages = [SimpleNamespace(role="user", content="test")]
        with patch("app.services.ai_service.GeminiProvider") as provider:
            provider.return_value.generate.side_effect = api_error(401)
            with self.assertLogs("app.services.ai_service", level="ERROR") as logs:
                with self.assertRaises(errors.APIError):
                    generate_chat_response(messages)
            self.assertIn("401", " ".join(logs.output))
            self.assertNotIn("PRIVATE_API_DETAIL", " ".join(logs.output))
            def partial_stream():
                yield "Partial"
                raise api_error(503)
            provider.return_value.stream_generate.return_value = partial_stream()
            stream = generate_chat_response_stream(messages)
            self.assertEqual(next(stream), "Partial")
            with self.assertRaises(errors.APIError):
                next(stream)


if __name__ == "__main__":
    unittest.main()
