import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import httpx

from scripts import validate_public_cases
from tests.helpers import CASES


class PublicCaseRunnerTests(unittest.TestCase):
    def test_single_case_offline_does_not_run_whole_suite(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["runner", "--offline", "--case", "SAMPLE-01"]), contextlib.redirect_stdout(output):
            self.assertEqual(validate_public_cases.main(), 0)
        self.assertIn("requests=1 failures=0", output.getvalue())
        self.assertNotIn("SAMPLE-02", output.getvalue())

    def test_unknown_id_fails_before_opening_http_client(self):
        with patch.object(sys, "argv", ["runner", "--base-url", "https://api.example", "--case", "UNKNOWN"]), \
                patch.object(validate_public_cases.httpx, "Client") as client, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                validate_public_cases.main()
            client.assert_not_called()

    def test_multiple_selected_cases_are_not_duplicated(self):
        output = io.StringIO()
        with patch.object(sys, "argv", ["runner", "--offline", "--case", "SAMPLE-01", "--case", "SAMPLE-02", "--case", "SAMPLE-01"]), \
                contextlib.redirect_stdout(output):
            self.assertEqual(validate_public_cases.main(), 0)
        self.assertIn("requests=2 failures=0", output.getvalue())

    def test_selected_live_request_uses_replay_without_more_requests(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=CASES[0]["expected_output"])

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(sys, "argv", ["runner", "--base-url", "https://api.example", "--case", "SAMPLE-01"]), \
                patch.object(validate_public_cases.httpx, "Client", return_value=client), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(validate_public_cases.main(), 0)
        self.assertEqual(len(calls), 1)