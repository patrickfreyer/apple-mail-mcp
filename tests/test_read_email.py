"""read_email tests; all Mail calls are mocked."""
import json
import unittest
from unittest.mock import patch

from apple_mail_mcp.tools import read


def payload(body="hello", attachments=()):
    fields = ["Subject | %7C\nnext", "Alice <a@example.com>", "Thursday", "12345",
              "<rfc@example.com>", "2", "b@example.com", "c@example.com",
              "1", "d@example.com", str(len(attachments))]
    for name, mime, size in attachments:
        fields.extend([name, mime, str(size)])
    fields.append(body)
    return "".join(s.replace("%", "%25").replace("|", "%7C") + "|" for s in fields)


class ReadEmailTests(unittest.TestCase):
    def call_read(self, body="hello", attachments=(), **kwargs):
        with patch.object(read, "run_applescript", return_value=payload(body, attachments)) as run:
            result = read.read_email("Work", " 12345 ", **kwargs)
        return result, run.call_args[0][0]

    def test_invalid_arguments_never_run_script(self):
        for kwargs in ({"message_id": "<rfc>"}, {"message_id": "123 or 1"},
                       {"message_id": ""}, {"message_id": "１２３"},
                       {"max_chars": 0}, {"max_chars": -1}, {"output_format": "xml"}):
            with self.subTest(kwargs=kwargs), patch.object(read, "run_applescript") as run:
                args = dict(account="Work", message_id="12345")
                args.update(kwargs)
                self.assertTrue(read.read_email(**args).startswith("Error:"))
                run.assert_not_called()

    def test_direct_lookup_no_message_scan(self):
        for mailbox in ("INBOX", "Archive", "Projects/2026"):
            result, script = self.call_read(mailbox=mailbox)
            self.assertIn("Subject:", result)
            self.assertIn("set targetMessage to «class mssg» id 12345 of targetMailbox", script)
            self.assertNotIn("whose", script.lower())
            self.assertNotIn("messages of", script.lower())
            self.assertNotIn("every message", script.lower())
            for expression in ("content of targetMessage", "mail attachments of targetMessage",
                               "MIME type of anAttachment", "file size of anAttachment",
                               "to recipients of targetMessage", "cc recipients of targetMessage",
                               "address of item", "message id of targetMessage"):
                self.assertIn(expression, script)
            self.assertNotIn("source of", script)

    def test_quotes_escaped(self):
        with patch.object(read, "run_applescript", return_value=payload()) as run:
            read.read_email('W"ork', "12345", mailbox='A"rchive')
        script = run.call_args[0][0]
        self.assertIn('account "W\\"ork"', script)
        self.assertIn('mailbox "A\\"rchive"', script)

    def test_headers_recipients_and_empty_attachments(self):
        result, _ = self.call_read(output_format="json")
        data = json.loads(result)
        self.assertEqual(data['subject'], "Subject | %7C\nnext")
        self.assertEqual(data['sender'], 'Alice <a@example.com>')
        self.assertEqual(data['date_received'], 'Thursday')
        self.assertEqual(data['message_id'], '12345')
        self.assertEqual(data['internet_message_id'], '<rfc@example.com>')
        self.assertEqual(data['to'], ['b@example.com', 'c@example.com'])
        self.assertEqual(data['cc'], ['d@example.com'])
        self.assertEqual(data['attachments'], [])

    def test_two_attachments_and_body_delimiters_newlines(self):
        body = "\nhello ||| %7C\nworld 😀\n  "
        attachments = [('one|%.pdf', 'application/pdf', 123), ('two.txt', 'text/plain', 42)]
        result, script = self.call_read(body, attachments, output_format="json")
        data = json.loads(result)
        self.assertEqual(data['body'], body)
        self.assertEqual(data['attachments'], [
            dict(name=name, mime_type=mime, file_size=size) for name, mime, size in attachments])
        self.assertIn('text item delimiters to "%25"', script)
        self.assertIn('text item delimiters to "%7C"', script)

    def test_text_truncation(self):
        result, _ = self.call_read('abcdefgh', max_chars=3)
        self.assertTrue(result.endswith('\nabc\n[truncated at 3 of 8 characters]'))

    def test_json_truncation(self):
        result, _ = self.call_read('😀abcdefg', max_chars=3, output_format="json")
        data = json.loads(result)
        self.assertEqual(data['body'], '😀ab')
        self.assertTrue(data['body_truncated'])
        self.assertEqual(data['body_total_chars'], 8)

    def test_under_and_at_cap(self):
        for cap in (5, 20):
            result, _ = self.call_read(max_chars=cap)
            self.assertTrue(result.endswith('\nhello'))
            self.assertNotIn('truncated', result)
            result, _ = self.call_read(max_chars=cap, output_format="json")
            self.assertFalse(json.loads(result)['body_truncated'])

    def test_not_found(self):
        error = 'Error: message 12345 not found in mailbox Archive of account Work'
        with patch.object(read, 'run_applescript', return_value=error) as run:
            self.assertEqual(read.read_email('Work', '12345', mailbox='Archive'), error)
        self.assertIn('return "' + error + '"', run.call_args[0][0])

    def test_execution_failure(self):
        with patch.object(read, 'run_applescript', side_effect=Exception('timeout')):
            self.assertIn('Error: could not read message 12345: timeout',
                          read.read_email('Work', '12345'))

    def test_malformed_response(self):
        with patch.object(read, 'run_applescript', return_value='bad response'):
            self.assertTrue(read.read_email('Work', '12345').startswith('Error: could not parse'))



class ReadEmailAttachmentSizeTests(unittest.TestCase):
    def test_missing_attachment_size_does_not_break_the_read(self):
        with patch.object(read, "run_applescript",
                          return_value=payload(attachments=[("a.pdf", "application/pdf", "")])):
            result = read.read_email("Work", "12345", output_format="json")
        data = json.loads(result)
        self.assertEqual(data["attachments"], [
            {"name": "a.pdf", "mime_type": "application/pdf", "file_size": None}])
        self.assertEqual(data["body"], "hello")

    def test_missing_mime_type_does_not_break_the_read(self):
        # Mail raises -10000 for `MIME type` on some Exchange attachments; the
        # script sends an empty field and the read still succeeds.
        with patch.object(read, "run_applescript",
                          return_value=payload(attachments=[("a.pdf", "", 2294)])) as run:
            result = read.read_email("Work", "12345", output_format="json")
        data = json.loads(result)
        self.assertEqual(data["attachments"], [
            {"name": "a.pdf", "mime_type": None, "file_size": 2294}])
        self.assertIn('my attachmentField(anAttachment, "mime")', run.call_args[0][0])


if __name__ == '__main__':
    unittest.main()
