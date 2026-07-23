# -*- coding: utf-8 -*-
"""Review screen: see what the AI wrote, edit it, then decide what to keep."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Generating is synchronous, so keep interactive batches small enough to
# finish before the browser gives up.
MAX_REVIEW_RECORDS = 20


class AIAgentRunWizard(models.TransientModel):
    _name = "ai.agent.run.wizard"
    _description = "AI Agent Result Review"

    agent_id = fields.Many2one("ai.agent", string="Agent", required=True, readonly=True)
    res_model = fields.Char(required=True, readonly=True)
    res_ids = fields.Char(required=True, readonly=True)

    line_ids = fields.One2many("ai.agent.run.wizard.line", "wizard_id", string="Results")
    line_count = fields.Integer(compute="_compute_line_count")
    single_line_id = fields.Many2one(
        "ai.agent.run.wizard.line", compute="_compute_line_count", string="Result",
    )

    target_field_label = fields.Char(compute="_compute_target_field_label")
    output_mode = fields.Selection(related="agent_id.output_mode")

    @api.depends("line_ids")
    def _compute_line_count(self):
        for wizard in self:
            wizard.line_count = len(wizard.line_ids)
            wizard.single_line_id = wizard.line_ids[:1]

    @api.depends("agent_id")
    def _compute_target_field_label(self):
        for wizard in self:
            agent = wizard.agent_id
            if agent.output_mode == "chatter":
                wizard.target_field_label = _("the chatter")
            elif agent.target_field_id:
                wizard.target_field_label = agent.target_field_id.field_description
            else:
                wizard.target_field_label = _("the record")

    def _records(self):
        self.ensure_one()
        ids = [int(i) for i in (self.res_ids or "").split(",") if i.strip().isdigit()]
        return self.env[self.res_model].browse(ids).exists()

    def action_generate(self):
        """Run the agent for every selected record and collect the answers."""
        self.ensure_one()
        records = self._records()
        if len(records) > MAX_REVIEW_RECORDS:
            raise UserError(_(
                "You selected %(count)s records. Please run “%(agent)s” on at most "
                "%(max)s at a time so it stays responsive.",
                count=len(records), agent=self.agent_id.name, max=MAX_REVIEW_RECORDS,
            ))
        self.line_ids.unlink()
        lines = []
        for record in records:
            reply = self.agent_id._generate_for_record(record)
            lines.append(fields.Command.create({
                "res_id": record.id,
                "record_name": record.display_name,
                "result": reply,
            }))
        self.line_ids = lines
        return True

    def action_regenerate(self):
        """Ask the AI again — useful when the first answer missed the mark."""
        self.ensure_one()
        self.action_generate()
        return self._reopen()

    def action_apply(self):
        """Save the ticked results onto their records."""
        self.ensure_one()
        agent = self.agent_id
        selected = self.line_ids.filtered("selected")
        if not selected:
            raise UserError(_("Tick at least one result to keep, or press Discard."))
        model = self.env[self.res_model]
        for line in selected:
            record = model.browse(line.res_id).exists()
            if record:
                agent._apply_result(record, line.result or "")
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Saved"),
                "message": _("%(count)s result(s) saved to %(target)s.",
                             count=len(selected), target=self.target_field_label),
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": self.agent_id.name,
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class AIAgentRunWizardLine(models.TransientModel):
    _name = "ai.agent.run.wizard.line"
    _description = "AI Agent Result Line"

    wizard_id = fields.Many2one("ai.agent.run.wizard", required=True, ondelete="cascade")
    res_id = fields.Integer(required=True)
    record_name = fields.Char(string="Record", readonly=True)
    result = fields.Text(
        string="AI Answer",
        help="You can edit this text before saving it.",
    )
    selected = fields.Boolean(string="Keep", default=True)
