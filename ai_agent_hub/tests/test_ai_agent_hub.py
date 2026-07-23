# -*- coding: utf-8 -*-
"""Tests run without touching the network: the provider call is patched."""
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

FAKE_REPLY = "A crisp, friendly description."


@tagged("post_install", "-at_install")
class TestAIAgentHub(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider = cls.env["ai.provider"].create({
            "name": "Test Provider",
            "api_type": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "test-key",
            "needs_key": True,
        })
        cls.partner_model = cls.env["ir.model"]._get("res.partner")
        cls.field_name = cls.env["ir.model.fields"]._get("res.partner", "name")
        cls.field_comment = cls.env["ir.model.fields"]._get("res.partner", "comment")
        cls.agent = cls.env["ai.agent"].create({
            "name": "Describe Partner",
            "provider_id": cls.provider.id,
            "model_id": cls.partner_model.id,
            "instruction": "Write a one-line summary.",
            "field_ids": [(6, 0, [cls.field_name.id])],
            "output_mode": "field",
            "target_field_id": cls.field_comment.id,
        })
        cls.partner = cls.env["res.partner"].create({"name": "Acme Industries"})

    # ------------------------------------------------------------------
    # Provider
    # ------------------------------------------------------------------
    def test_provider_without_key_raises_friendly_error(self):
        provider = self.env["ai.provider"].create({
            "name": "Keyless",
            "api_type": "openai",
            "base_url": "https://example.invalid/v1",
            "model": "m",
            "needs_key": True,
        })
        with self.assertRaises(UserError) as err:
            provider.chat("system", "user")
        self.assertIn("API key", str(err.exception))

    def test_default_provider_falls_back(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "ai_agent_hub.default_provider_id", "999999999",
        )
        self.assertTrue(self.env["ai.provider"]._get_default_provider())

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------
    def test_prompt_contains_only_ticked_fields(self):
        prompt = self.agent._build_user_prompt(self.partner)
        self.assertIn("Acme Industries", prompt)
        # 'comment' was never ticked, so its label must not appear.
        self.assertNotIn(self.field_comment.field_description, prompt)

    def test_prompt_handles_empty_record(self):
        blank = self.env["res.partner"].create({"name": ""})
        self.assertTrue(self.agent._build_user_prompt(blank))

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def test_run_writes_into_html_target_as_markup(self):
        """res.partner.comment is an Html field, so the text is wrapped in <p>."""
        with patch.object(
            type(self.provider), "chat", return_value=(FAKE_REPLY, 0.1),
        ):
            self.agent.run_on_records(self.partner)
        self.assertIn(FAKE_REPLY, self.partner.comment)
        self.assertTrue(str(self.partner.comment).startswith("<p>"))

    def test_run_writes_into_text_target_verbatim(self):
        """A plain Char/Text target gets exactly what the AI returned."""
        self.agent.target_field_id = self.env["ir.model.fields"]._get("res.partner", "ref")
        with patch.object(
            type(self.provider), "chat", return_value=(FAKE_REPLY, 0.1),
        ):
            self.agent.run_on_records(self.partner)
        self.assertEqual(self.partner.ref, FAKE_REPLY)

    def test_html_target_keeps_paragraph_breaks(self):
        self.agent.target_field_id = self.field_comment
        with patch.object(
            type(self.provider), "chat", return_value=("First line.\n\nSecond line.", 0.1),
        ):
            self.agent.run_on_records(self.partner)
        self.assertIn("</p><p>", str(self.partner.comment))

    def test_run_creates_history_entry(self):
        with patch.object(
            type(self.provider), "chat", return_value=(FAKE_REPLY, 0.1),
        ):
            self.agent.run_on_records(self.partner)
        log = self.env["ai.request.log"].search([("agent_id", "=", self.agent.id)], limit=1)
        self.assertEqual(log.state, "done")
        self.assertEqual(log.response, FAKE_REPLY)
        self.assertEqual(log.res_id, self.partner.id)

    def test_run_on_wrong_model_is_rejected(self):
        company = self.env["res.company"].browse(self.env.company.id)
        with self.assertRaises(UserError):
            self.agent.run_on_records(company)

    def test_run_without_records_is_rejected(self):
        with self.assertRaises(UserError):
            self.agent.run_on_records(self.env["res.partner"])

    # ------------------------------------------------------------------
    # Review wizard
    # ------------------------------------------------------------------
    def test_review_mode_does_not_write_until_applied(self):
        self.agent.output_mode = "review"
        with patch.object(
            type(self.provider), "chat", return_value=(FAKE_REPLY, 0.1),
        ):
            action = self.agent.run_on_records(self.partner)
        self.assertEqual(action["res_model"], "ai.agent.run.wizard")
        self.assertFalse(self.partner.comment, "nothing may be saved before approval")

        wizard = self.env["ai.agent.run.wizard"].browse(action["res_id"])
        self.assertEqual(len(wizard.line_ids), 1)
        self.assertEqual(wizard.line_ids.result, FAKE_REPLY)

        wizard.line_ids.result = "Edited by the user."
        wizard.action_apply()
        self.assertIn("Edited by the user.", self.partner.comment)

    def test_review_apply_requires_a_selection(self):
        self.agent.output_mode = "review"
        with patch.object(
            type(self.provider), "chat", return_value=(FAKE_REPLY, 0.1),
        ):
            action = self.agent.run_on_records(self.partner)
        wizard = self.env["ai.agent.run.wizard"].browse(action["res_id"])
        wizard.line_ids.selected = False
        with self.assertRaises(UserError):
            wizard.action_apply()

    # ------------------------------------------------------------------
    # Configuration guardrails
    # ------------------------------------------------------------------
    def test_target_field_must_be_text_like(self):
        with self.assertRaises(UserError):
            self.agent.target_field_id = self.env["ir.model.fields"]._get(
                "res.partner", "is_company",
            )

    def test_fields_must_belong_to_the_model(self):
        with self.assertRaises(UserError):
            self.agent.field_ids = [(6, 0, [
                self.env["ir.model.fields"]._get("res.company", "name").id,
            ])]

    def test_agent_appears_in_actions_menu(self):
        self.assertTrue(self.agent.server_action_id)
        self.assertEqual(
            self.agent.server_action_id.binding_model_id, self.partner_model,
        )

    def test_hiding_agent_removes_the_binding(self):
        self.agent.show_in_actions = False
        self.assertFalse(self.agent.server_action_id.binding_model_id)
