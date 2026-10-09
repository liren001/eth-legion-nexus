import unittest
from unittest.mock import patch
import tempfile
import json
import os
from pathlib import Path
import engine_redacted as engine

class RegressionTests(unittest.TestCase):
    def test_unpack_and_fetch_failures_are_loud(self):
        source = 'https://example.org/index.htm'
        page = '<a href="./202610/t1_2.htm">A sufficiently long title</a>'
        with tempfile.TemporaryDirectory() as tmp, patch.object(engine, 'LEADS_ALL', Path(tmp)/'missing'), patch.object(engine, 'SOURCES', [source]), patch.object(engine.time, 'sleep'), patch.object(engine, 'mailto') as send:
            # Seed the incorrect tuple arity at the ingestion boundary.
            with patch.object(engine, 'fetch', return_value=page), patch.object(engine.re, 'findall', return_value=[('./202610/t1_2.htm', 'title', 'extra')]), self.assertLogs(engine.LOG, level='ERROR') as logs:
                self.assertEqual(engine.main(), 2)
                self.assertIn('stage=list', logs.output[0])
            # A tuple returned by detail fetch must never masquerade as no leads.
            with patch.object(engine, 'fetch', side_effect=[page, ('body', 200)]), self.assertLogs(engine.LOG, level='ERROR') as logs:
                self.assertEqual(engine.main(), 2)
                self.assertIn('stage=detail', logs.output[0])
            # Reintroduce an unpacking exception inside the detail fetch.
            def broken(url):
                if url == source:
                    return page
                first, second = ('only-one',)
                return first
            with patch.object(engine, 'fetch', side_effect=broken), self.assertLogs(engine.LOG, level='ERROR') as logs:
                self.assertEqual(engine.main(), 2)
                self.assertIn('type=ValueError', logs.output[0])
            with patch.object(engine, 'fetch', return_value=''):
                self.assertEqual(engine.main(), 0)
            send.assert_not_called()
        self.assertEqual(engine.detail_url(source, './202610/t1_2.htm'), 'https://example.org/202610/t1_2.htm')
        for bad in ['javascript:alert(1)', 'https://user:pass@example.org/', 'https://example.org:bad/']:
            with self.assertRaises(ValueError): engine.validate_url(bad)

    def test_email_rejection_and_legitimate_cases(self):
        # Synthetic examples; client fixture files are currently empty.
        reject = ['%E6%96%87@qq.com', 'hello@example.c0m', 'x'*41+'@example.org']
        accept = ['hello@example.org', 'first.last@example.com', 'ops+tag@sub.example.org', 'x'*40+'@example.net']
        if os.environ.get('TASK001_CLIENT_FIXTURES') == '1':
            reject = json.loads(Path(__file__).with_name('fixtures_reject.json').read_text())
            accept = json.loads(Path(__file__).with_name('fixtures_pass.json').read_text())
            self.assertIsInstance(reject, list)
            self.assertIsInstance(accept, list)
            self.assertEqual(len(reject), 3)
            self.assertEqual(len(accept), 4)
        for email in reject:
            with self.subTest(email=email): self.assertFalse(engine.valid_email(email))
        for email in accept:
            with self.subTest(email=email): self.assertTrue(engine.valid_email(email))
        page = '<a href="./202610/t1_2.htm">A sufficiently long title</a>'
        with tempfile.TemporaryDirectory() as tmp, patch.object(engine, 'LEADS_ALL', Path(tmp)/'missing'), patch.object(engine, 'SOURCES', ['https://example.org/index.htm']), patch.object(engine.time, 'sleep'), patch.object(engine, 'fetch', side_effect=[page, ' '.join(reject+accept)]):
            status = engine.RunStatus()
            self.assertEqual({x['email'] for x in engine.collect(status)}, set(accept))
            self.assertEqual(status.exit_code, 0)

if __name__ == '__main__': unittest.main()
