# -*- coding: utf-8 -*-
{
    "name": "AI Agents for Odoo (Community & Enterprise)",
    "summary": "Bring AI to any Odoo screen - free providers, no coding. Works on Community, Enterprise and Odoo.sh",
    "description": """
AI Agents for Odoo
==================

Give any Odoo record an AI agent - on Community, Enterprise or Odoo.sh, with the
AI provider of your choice. On Community it brings the AI features Odoo 19 keeps
for Enterprise; on Enterprise and Odoo.sh it adds free provider choice with no
per-feature lock-in.

Create an AI agent in a few clicks and run it from the **Actions** menu of *any*
screen in Odoo - Sales, CRM, Products, HR, Helpdesk, your own custom models.

* **Works for free.** Groq, Google Gemini and OpenRouter all have free API keys.
  Ollama runs on your own machine with no key and no internet at all.
* **No coding, no developer mode.** Tick the fields the AI should look at,
  write what you want in plain English, choose where the answer goes.
* **Nothing is overwritten behind your back.** By default every result is shown
  to you first so you can edit it before it is saved.
* **Full history.** Every request is logged with timing, cost and result.
""",
    "author": "Zarki",
    "website": "https://github.com/zarkidev/odoo-ai-agent-hub",
    "license": "LGPL-3",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["base", "mail"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ai_agent_hub_security.xml",
        "security/ir.model.access.csv",
        "data/ai_provider_data.xml",
        "views/ai_provider_views.xml",
        "views/ai_agent_views.xml",
        "views/ai_request_log_views.xml",
        "wizard/ai_agent_run_wizard_views.xml",
        "views/res_config_settings_views.xml",
        "views/ai_agent_hub_menus.xml",
    ],
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": True,
}
