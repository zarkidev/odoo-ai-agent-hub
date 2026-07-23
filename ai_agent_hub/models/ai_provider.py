# -*- coding: utf-8 -*-
"""AI provider records.

Each provider is a normal Odoo record with its endpoint and default model
already filled in, so the only thing a user has to supply is an API key
(and even that is not needed for Ollama).
"""
import logging
import time

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 90

# Which request format each provider speaks.
API_OPENAI = "openai"        # OpenAI-compatible /chat/completions
API_ANTHROPIC = "anthropic"  # Anthropic Messages API
API_OLLAMA = "ollama"        # local Ollama /api/chat


class AIProvider(models.Model):
    _name = "ai.provider"
    _description = "AI Provider"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)

    api_type = fields.Selection(
        selection=[
            (API_OPENAI, "OpenAI compatible"),
            (API_ANTHROPIC, "Anthropic"),
            (API_OLLAMA, "Ollama (local)"),
        ],
        string="API Format",
        required=True,
        default=API_OPENAI,
        help="How requests are sent. Most providers use the OpenAI format.",
    )
    base_url = fields.Char(
        string="API Address",
        required=True,
        help="The provider endpoint. Already filled in for you - only change it "
             "if the provider tells you to.",
    )
    model = fields.Char(
        string="AI Model",
        required=True,
        help="The model name to use, e.g. llama-3.3-70b-versatile.",
    )
    api_key = fields.Char(
        string="API Key",
        groups="ai_agent_hub.group_ai_manager",
        help="Paste the key you got from the provider's website.",
    )
    needs_key = fields.Boolean(
        string="Requires an API Key",
        default=True,
    )
    is_free = fields.Boolean(
        string="Free to use",
        help="Ticked for providers that offer a free key or run locally.",
    )
    signup_url = fields.Char(
        string="Where to get a key",
        help="Link to the page where a free API key can be created.",
    )
    temperature = fields.Float(
        string="Creativity",
        default=0.7,
        help="0 = precise and factual. 1 = more creative and varied.",
    )
    max_tokens = fields.Integer(
        string="Maximum Length",
        default=1024,
        help="Roughly how long the answer can be. 1000 is about 750 words.",
    )

    # --- status shown in the form so the user always knows where they stand ---
    state = fields.Selection(
        selection=[
            ("draft", "Not tested"),
            ("ready", "Working"),
            ("error", "Not working"),
        ],
        default="draft",
        readonly=True,
        string="Status",
    )
    state_message = fields.Text(string="Last Test Result", readonly=True)

    _name_uniq = models.Constraint(
        "unique (name)",
        "An AI provider with this name already exists.",
    )

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_default_provider(self):
        """Return the provider chosen in Settings, or the first working one."""
        icp = self.env["ir.config_parameter"].sudo()
        provider_id = icp.get_param("ai_agent_hub.default_provider_id")
        if provider_id:
            provider = self.browse(int(provider_id)).exists()
            if provider:
                return provider
        return self.search([("state", "=", "ready")], limit=1) or self.search([], limit=1)

    def _check_ready(self):
        """Raise a friendly error if this provider cannot be used yet."""
        self.ensure_one()
        if self.needs_key and not self.api_key:
            raise UserError(_(
                "The AI provider '%(name)s' still needs an API key.\n\n"
                "Open AI -> Configuration -> Providers, select '%(name)s' and paste your key.\n"
                "%(hint)s",
                name=self.name,
                hint=_("You can create a free key at %s", self.signup_url) if self.signup_url else "",
            ))

    # ------------------------------------------------------------------
    # Public API used by agents
    # ------------------------------------------------------------------
    def chat(self, system_prompt, user_prompt):
        """Send the prompts to this provider and return the reply as text."""
        self.ensure_one()
        self._check_ready()
        started = time.time()
        try:
            if self.api_type == API_ANTHROPIC:
                reply = self._call_anthropic(system_prompt, user_prompt)
            elif self.api_type == API_OLLAMA:
                reply = self._call_ollama(system_prompt, user_prompt)
            else:
                reply = self._call_openai(system_prompt, user_prompt)
        except requests.exceptions.Timeout:
            raise UserError(_(
                "'%s' took too long to answer. Please try again, or pick a smaller model.",
                self.name,
            ))
        except requests.exceptions.RequestException as err:
            _logger.warning("AI provider %s unreachable: %s", self.name, err)
            raise UserError(_(
                "Could not reach '%(name)s'.\n\n%(error)s",
                name=self.name, error=err,
            ))
        except (KeyError, IndexError, ValueError) as err:
            _logger.warning("Unexpected response from %s: %s", self.name, err)
            raise UserError(_(
                "'%s' sent back something unexpected. Please try again.", self.name,
            ))
        return reply, time.time() - started

    # ------------------------------------------------------------------
    # Per-format request builders
    # ------------------------------------------------------------------
    def _endpoint(self, path):
        return "%s/%s" % ((self.base_url or "").rstrip("/"), path.lstrip("/"))

    def _call_openai(self, system_prompt, user_prompt):
        response = requests.post(
            self._endpoint("chat/completions"),
            headers={
                "Authorization": "Bearer %s" % (self.api_key or ""),
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "temperature": self.temperature,
                "max_tokens": self.max_tokens or 1024,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=REQUEST_TIMEOUT,
        )
        self._raise_for_api_error(response)
        return response.json()["choices"][0]["message"]["content"].strip()

    def _call_anthropic(self, system_prompt, user_prompt):
        response = requests.post(
            self._endpoint("messages"),
            headers={
                "x-api-key": self.api_key or "",
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "max_tokens": self.max_tokens or 1024,
                "temperature": self.temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
            timeout=REQUEST_TIMEOUT,
        )
        self._raise_for_api_error(response)
        return response.json()["content"][0]["text"].strip()

    def _call_ollama(self, system_prompt, user_prompt):
        response = requests.post(
            self._endpoint("api/chat"),
            json={
                "model": self.model,
                "stream": False,
                "options": {"temperature": self.temperature},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
            timeout=REQUEST_TIMEOUT,
        )
        self._raise_for_api_error(response)
        return response.json()["message"]["content"].strip()

    def _raise_for_api_error(self, response):
        if response.status_code < 400:
            return
        detail = response.text
        try:
            payload = response.json()
            if isinstance(payload, dict):
                err = payload.get("error", payload)
                detail = err.get("message", detail) if isinstance(err, dict) else str(err)
        except ValueError:
            pass
        # Turn the most common failures into advice instead of a raw error code.
        if response.status_code in (401, 403):
            raise UserError(_(
                "'%(name)s' rejected your API key.\n\n"
                "Check that the key is correct and still active, then test again.\n\n"
                "Details: %(detail)s",
                name=self.name, detail=detail,
            ))
        if response.status_code == 404:
            raise UserError(_(
                "'%(model)s' was not found on %(name)s.\n\n"
                "The model name may be wrong or no longer available. "
                "Open AI -> Configuration -> Providers to change it.\n\n"
                "Details: %(detail)s",
                model=self.model, name=self.name, detail=detail,
            ))
        if response.status_code == 429:
            raise UserError(_(
                "'%(name)s' is rate limiting you - too many requests, or the free "
                "quota is used up. Wait a moment and try again.\n\n"
                "Details: %(detail)s",
                name=self.name, detail=detail,
            ))
        raise UserError(_(
            "'%(name)s' returned an error (%(code)s).\n\n%(detail)s",
            name=self.name, code=response.status_code, detail=detail,
        ))

    # ------------------------------------------------------------------
    # Buttons
    # ------------------------------------------------------------------
    def action_test_connection(self):
        """Send a tiny prompt so the user gets a clear yes/no before building agents."""
        self.ensure_one()
        try:
            reply, _duration = self.chat(
                "You are a helpful assistant. Answer with a single word.",
                "Reply with the word: OK",
            )
        except UserError as err:
            self.write({"state": "error", "state_message": str(err)})
            # Re-raise so the user sees the actionable message immediately.
            raise
        self.write({
            "state": "ready",
            "state_message": _("Connection successful. The AI replied: %s", reply[:200]),
        })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "type": "success",
                "title": _("%s is working", self.name),
                "message": _("You can now use this provider in your AI agents."),
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
