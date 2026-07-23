# -*- coding: utf-8 -*-
"""History of every AI call, so nothing the AI does is invisible."""
from odoo import _, fields, models


class AIRequestLog(models.Model):
    _name = "ai.request.log"
    _description = "AI Request History"
    _order = "create_date desc, id desc"
    _rec_name = "record_name"

    agent_id = fields.Many2one("ai.agent", string="Agent", ondelete="set null", index=True)
    provider_id = fields.Many2one("ai.provider", string="Provider", ondelete="set null")
    ai_model = fields.Char(string="AI Model")

    res_model = fields.Char(string="Record Type")
    res_id = fields.Integer(string="Record ID")
    record_name = fields.Char(string="Record")

    prompt = fields.Text(string="Sent to the AI")
    response = fields.Text(string="AI Answer")
    duration = fields.Float(string="Took (seconds)", digits=(6, 2))

    state = fields.Selection(
        selection=[("done", "Success"), ("error", "Failed")],
        string="Result",
        default="done",
        index=True,
    )
    error_message = fields.Text(string="What went wrong")

    def action_open_record(self):
        """Jump from a history line back to the record it ran on."""
        self.ensure_one()
        if not self.res_model or not self.res_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": self.record_name or _("Record"),
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
        }
