# -*- coding: utf-8 -*-
"""AI agents.

An agent is "run this instruction, on this kind of record, using these fields,
and put the answer here". No template syntax and no developer mode required:
the user ticks the fields the AI should look at and Odoo builds the prompt.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Fields the AI should never be asked to read or write.
BLOCKED_FIELDS = {
    "id", "create_uid", "create_date", "write_uid", "write_date",
    "__last_update", "display_name", "password", "api_key",
}

# Fields the answer can be written into.
WRITABLE_TYPES = ("char", "text", "html")


class AIAgent(models.Model):
    _name = "ai.agent"
    _description = "AI Agent"
    _order = "sequence, name"

    name = fields.Char(
        string="Agent Name",
        required=True,
        translate=True,
        help="How this agent appears in the Actions menu, e.g. 'Summarise this lead'.",
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    note = fields.Text(string="Internal Note")

    provider_id = fields.Many2one(
        "ai.provider",
        string="AI Provider",
        required=True,
        default=lambda self: self.env["ai.provider"]._get_default_provider(),
        ondelete="restrict",
        help="Which AI service answers. Leave as-is to use your default.",
    )

    model_id = fields.Many2one(
        "ir.model",
        string="Use On",
        required=True,
        ondelete="cascade",
        domain=[("transient", "=", False)],
        help="The kind of record this agent runs on, e.g. Lead, Product, Employee.",
    )
    model_name = fields.Char(related="model_id.model", store=True, string="Model Name")

    instruction = fields.Text(
        string="What should the AI do?",
        required=True,
        translate=True,
        help="Describe the task in plain English, as if briefing a colleague. "
             "Example: 'Write a short, friendly product description highlighting "
             "the main benefits. Use two sentences.'",
    )

    field_ids = fields.Many2many(
        "ir.model.fields",
        "ai_agent_field_rel",
        "agent_id",
        "field_id",
        string="Information to Send",
        help="Tick the fields the AI is allowed to look at. Only these are sent.",
    )

    output_mode = fields.Selection(
        selection=[
            ("review", "Show me the result first"),
            ("field", "Save straight into a field"),
            ("chatter", "Post in the chatter"),
        ],
        string="What to do with the answer",
        required=True,
        default="review",
        help="'Show me the result first' is the safest: nothing is saved until you approve it.",
    )
    target_field_id = fields.Many2one(
        "ir.model.fields",
        string="Save Into Field",
        ondelete="cascade",
        help="Which field the answer is written into.",
    )

    show_in_actions = fields.Boolean(
        string="Show in the Actions menu",
        default=True,
        help="Adds this agent to the ⚙ Actions menu of the selected records.",
    )
    server_action_id = fields.Many2one(
        "ir.actions.server", string="Action", readonly=True, ondelete="set null", copy=False,
    )

    log_ids = fields.One2many("ai.request.log", "agent_id", string="History")
    log_count = fields.Integer(compute="_compute_log_count", string="Runs")

    # ------------------------------------------------------------------
    # Computes / onchanges
    # ------------------------------------------------------------------
    def _compute_log_count(self):
        # Odoo 16 signature: _read_group(domain, fields, groupby) -> list of dicts.
        # (17.0 changed this to (domain, groupby, aggregates) returning tuples.)
        data = self.env["ai.request.log"]._read_group(
            [("agent_id", "in", self.ids)], ["agent_id"], ["agent_id"],
        )
        counts = {
            row["agent_id"][0]: row["agent_id_count"]
            for row in data if row.get("agent_id")
        }
        for agent in self:
            agent.log_count = counts.get(agent.id, 0)

    @api.onchange("model_id")
    def _onchange_model_id(self):
        """Clear field choices that belong to the previous model."""
        self.field_ids = [fields.Command.clear()]
        self.target_field_id = False

    @api.onchange("output_mode")
    def _onchange_output_mode(self):
        if self.output_mode == "chatter":
            self.target_field_id = False

    @api.constrains("output_mode", "target_field_id")
    def _check_target_field(self):
        for agent in self:
            if agent.output_mode == "field" and not agent.target_field_id:
                raise UserError(_(
                    "Choose which field the answer should be saved into, "
                    "or switch to 'Show me the result first'."
                ))
            target = agent.target_field_id
            if target and target.ttype not in WRITABLE_TYPES:
                raise UserError(_(
                    "The answer is text, so it cannot be saved into '%s'. "
                    "Pick a text, description or HTML field instead.",
                    target.field_description,
                ))

    @api.constrains("model_id", "field_ids", "target_field_id")
    def _check_fields_belong_to_model(self):
        for agent in self:
            wrong = (agent.field_ids | agent.target_field_id).filtered(
                lambda f: f.model_id != agent.model_id
            )
            if wrong:
                raise UserError(_(
                    "Some selected fields do not belong to %s. "
                    "Please re-pick them after changing 'Use On'.",
                    agent.model_id.name,
                ))

    # ------------------------------------------------------------------
    # Actions-menu binding
    # ------------------------------------------------------------------
    def _server_action_values(self):
        self.ensure_one()
        return {
            "name": self.name,
            "model_id": self.model_id.id,
            "binding_model_id": self.model_id.id if self.show_in_actions else False,
            "binding_type": "action",
            "state": "code",
            "code": "action = env['ai.agent'].browse(%d).run_on_records(records)" % self.id,
        }

    def _sync_server_action(self):
        for agent in self:
            if agent.show_in_actions and agent.active and agent.model_id:
                values = agent._server_action_values()
                if agent.server_action_id:
                    agent.server_action_id.sudo().write(values)
                else:
                    action = self.env["ir.actions.server"].sudo().create(values)
                    agent.server_action_id = action
            elif agent.server_action_id:
                agent.server_action_id.sudo().write({"binding_model_id": False})

    @api.model_create_multi
    def create(self, vals_list):
        agents = super().create(vals_list)
        agents._sync_server_action()
        return agents

    def write(self, vals):
        result = super().write(vals)
        if {"name", "model_id", "show_in_actions", "active"} & set(vals):
            self._sync_server_action()
        return result

    def unlink(self):
        self.server_action_id.sudo().unlink()
        return super().unlink()

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------
    def _readable_value(self, record, field):
        """Return a human-readable string for one field of one record."""
        value = record[field.name]
        if value in (False, None):
            return ""
        if field.ttype == "many2one":
            return value.display_name or ""
        if field.ttype in ("one2many", "many2many"):
            return ", ".join(value.mapped("display_name"))
        if field.ttype == "selection":
            return dict(record._fields[field.name]._description_selection(record.env)).get(value, value)
        if field.ttype == "html":
            return self.env["ir.fields.converter"].text_from_html(value) if hasattr(
                self.env["ir.fields.converter"], "text_from_html"
            ) else str(value)
        return str(value)

    def _build_user_prompt(self, record):
        """Turn the ticked fields into a simple, readable block of context."""
        self.ensure_one()
        lines = []
        for field in self.field_ids:
            if field.name in BLOCKED_FIELDS or field.name not in record._fields:
                continue
            try:
                value = self._readable_value(record, field)
            except Exception:  # a field that cannot be read must not break the run
                _logger.debug("Could not read %s on %s", field.name, record, exc_info=True)
                continue
            if value:
                lines.append("%s: %s" % (field.field_description, value))
        if not lines:
            lines.append(_("(no details available)"))
        return _(
            "Here are the details of the %(model)s record:\n\n%(details)s",
            model=self.model_id.name,
            details="\n".join(lines),
        )

    def _system_prompt(self):
        self.ensure_one()
        return _(
            "You are an assistant working inside the Odoo business system.\n"
            "Task: %(instruction)s\n\n"
            "Answer with the finished text only. Do not add explanations, "
            "greetings, or markdown code fences.",
            instruction=self.instruction,
        )

    # ------------------------------------------------------------------
    # Running
    # ------------------------------------------------------------------
    def _generate_for_record(self, record):
        """Call the provider for one record and log the outcome."""
        self.ensure_one()
        log_values = {
            "agent_id": self.id,
            "provider_id": self.provider_id.id,
            "ai_model": self.provider_id.model,
            "res_model": record._name,
            "res_id": record.id,
            "record_name": record.display_name,
        }
        user_prompt = self._build_user_prompt(record)
        try:
            # sudo(): the API key is manager-only, but any AI user may run an agent.
            reply, duration = self.provider_id.sudo().chat(self._system_prompt(), user_prompt)
        except UserError as err:
            self.env["ai.request.log"].sudo().create(dict(
                log_values, state="error", prompt=user_prompt, error_message=str(err),
            ))
            # Logs are kept even though the transaction will roll back the rest.
            raise
        self.env["ai.request.log"].sudo().create(dict(
            log_values, state="done", prompt=user_prompt,
            response=reply, duration=duration,
        ))
        return reply

    def run_on_records(self, records):
        """Entry point used by the Actions menu and by other modules."""
        self.ensure_one()
        if not records:
            raise UserError(_("Select at least one record first."))
        if records._name != self.model_name:
            raise UserError(_(
                "'%(agent)s' works on %(expected)s records, not on this kind of record.",
                agent=self.name, expected=self.model_id.name,
            ))

        if self.output_mode == "review":
            return self._action_open_review(records)

        for record in records:
            reply = self._generate_for_record(record)
            self._apply_result(record, reply)

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("Done"),
                "message": _("%(agent)s finished on %(count)s record(s).",
                             agent=self.name, count=len(records)),
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def _apply_result(self, record, text):
        """Write the answer where the user asked for it."""
        self.ensure_one()
        if self.output_mode == "chatter":
            if not hasattr(record, "message_post"):
                raise UserError(_(
                    "%s records have no chatter, so the answer cannot be posted there. "
                    "Choose a different option in the agent.",
                    self.model_id.name,
                ))
            record.message_post(body=text.replace("\n", "<br/>"))
            return
        target = self.target_field_id
        if not target:
            raise UserError(_("This agent has no field to save the answer into."))
        value = text
        if target.ttype == "html":
            value = "<p>%s</p>" % text.replace("\n\n", "</p><p>").replace("\n", "<br/>")
        record.write({target.name: value})

    def _action_open_review(self, records):
        """Open the review wizard so nothing is saved without approval."""
        self.ensure_one()
        wizard = self.env["ai.agent.run.wizard"].create({
            "agent_id": self.id,
            "res_model": records._name,
            "res_ids": ",".join(str(r) for r in records.ids),
        })
        wizard.action_generate()
        return {
            "type": "ir.actions.act_window",
            "name": self.name,
            "res_model": "ai.agent.run.wizard",
            "res_id": wizard.id,
            "view_mode": "form",
            "target": "new",
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("History"),
            "res_model": "ai.request.log",
            "view_mode": "list,form",
            "domain": [("agent_id", "=", self.id)],
            "context": {"default_agent_id": self.id},
        }
