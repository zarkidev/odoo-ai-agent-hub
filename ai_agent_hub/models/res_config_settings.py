# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_default_provider_id = fields.Many2one(
        "ai.provider",
        string="Default AI Provider",
        config_parameter="ai_agent_hub.default_provider_id",
        help="Used by new agents. Each agent can still use a different provider.",
    )
    ai_provider_state = fields.Selection(
        related="ai_default_provider_id.state", string="Provider Status", readonly=True,
    )

    def action_open_ai_providers(self):
        return self.env["ir.actions.actions"]._for_xml_id(
            "ai_agent_hub.action_ai_provider"
        )

    @api.model
    def get_values(self):
        values = super().get_values()
        # config_parameter stores the id as a string; make sure a deleted
        # provider does not break the settings screen.
        provider_id = values.get("ai_default_provider_id")
        if provider_id and not self.env["ai.provider"].browse(int(provider_id)).exists():
            values["ai_default_provider_id"] = False
        return values
