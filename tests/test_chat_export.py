import unittest
from unittest.mock import patch

from chat_export import chat_markdown, render_chat_download


class ChatExportTest(unittest.TestCase):
    def test_visible_transcript_order_and_private_fields_excluded(self):
        for role in ("PIA", "AILA"):
            with self.subTest(role=role):
                activity = {"role": role, "activity_name": "Kabel und Tester",
                            "role_framework": "PRIVATE_FRAMEWORK", "system_info": "PRIVATE_ANSWER",
                            "tasks": [{"conversation": [{"message": "UNREVEALED"}]}]}
                state = {"participant_code": "STUDY_ID", "session": "PRIVATE_SESSION",
                         "task_markers": [{"message_index": 0, "task_title": "Einstieg"},
                                          {"message_index": 2, "task_title": "Muster erkennen"}],
                         "messages": [{"role": "assistant", "content": "Hallo!"},
                                      {"role": "user", "content": "Grüß dich, **PIA**."},
                                      {"role": "assistant", "content": "Nächste Frage"}]}
                result = chat_markdown(activity, state)
                self.assertIn(f"**{role}:**", result)
                self.assertIn("**User:**", result)
                self.assertIn("Grüß dich, **PIA**.", result)
                self.assertLess(result.index("## Einstieg"), result.index("Hallo!"))
                self.assertLess(result.index("Grüß dich"), result.index("## Muster erkennen"))
                self.assertLess(result.index("## Muster erkennen"), result.index("Nächste Frage"))
                self.assertIn("Studienteilnehmer-ID: STUDY_ID", result)
                for private in ("PRIVATE_FRAMEWORK", "PRIVATE_ANSWER", "UNREVEALED", "PRIVATE_SESSION"):
                    self.assertNotIn(private, result)

    def test_message_timestamps_are_exported_in_vienna_time_for_both_speakers(self):
        state = {"messages": [
            {"role": "user", "content": "Hallo", "timestamp": "2026-11-12T09:10:00+00:00"},
            {"role": "assistant", "content": "Hallo!", "timestamp": "2026-11-12T09:10:04+00:00"},
        ]}
        for role in ("PIA", "AILA"):
            result = chat_markdown({"role": role}, state, participant_code="B-123")
            self.assertIn("**User:** _12.11.2026 10:10:00 CET_", result)
            self.assertIn(f"**{role}:** _12.11.2026 10:10:04 CET_", result)
            self.assertIn("Studienteilnehmer-ID: B-123", result)
            self.assertIn("Zeitzone der Nachrichten: Europe/Vienna", result)

    def test_download_uses_explicit_study_id_and_does_not_invent_legacy_times(self):
        state = {"participant_code": "fallback", "messages": [{"role": "user", "content": "Hallo"}]}
        with patch("chat_export.st.download_button") as button:
            render_chat_download({"role": "AILA"}, state, participant_code="B-123")
        result = button.call_args.kwargs["data"].decode("utf-8")
        self.assertIn("Studienteilnehmer-ID: B-123", result)
        self.assertIn("Zeitstempel nicht verfügbar", result)
        self.assertNotIn("fallback", result)

    def test_images_and_bold_blocks_without_broken_local_links(self):
        state = {"messages": [
            {"role": "assistant", "content": "Schau: ![Zwei Kabel](figures/cables.png){width=520}"},
            {"role": "assistant", "type": "image", "content": "figures/tester.png"},
            {"role": "assistant", "type": "bold", "content": "Merke"},
        ]}
        result = chat_markdown({"role": "PIA"}, state)
        self.assertIn("_Abbildung: Zwei Kabel_", result)
        self.assertIn("_Abbildung im Chat_", result)
        self.assertIn("**Merke**", result)
        self.assertNotIn("figures/", result)
        self.assertNotIn("{width=", result)

    def test_empty_and_legacy_chat_without_markers(self):
        self.assertIn("# Chat", chat_markdown({}, {}))
        self.assertIn("Studienteilnehmer-ID: Nicht hinterlegt", chat_markdown({}, {}))
        result = chat_markdown({"role": "AILA"}, {"messages": [{"role": "user", "content": "Hallo"}]})
        self.assertIn("Hallo", result)


if __name__ == "__main__":
    unittest.main()
