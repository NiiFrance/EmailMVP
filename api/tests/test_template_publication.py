from unittest.mock import patch

import pytest

import prompt_templates


def test_template_list_refreshes_other_workers_changes():
    template = dict(prompt_templates.PROMPT_REGISTRY["leads"])
    template["archived"] = False
    with patch.object(prompt_templates, "_load_campaign_templates", return_value={"leads": template}) as load:
        assert any(item["id"] == "leads" for item in prompt_templates.list_templates())
        load.assert_called_once_with(force=True)


def test_generation_cannot_select_unpublished_or_archived_template():
    template = dict(prompt_templates.PROMPT_REGISTRY["leads"], archived=True)
    with patch.object(prompt_templates, "_load_campaign_templates", return_value={"leads": template}) as load:
        with pytest.raises(KeyError):
            prompt_templates.get_template("leads")
        load.assert_called_once_with(force=True)


def test_empty_table_retains_builtin_fallback():
    with patch.object(prompt_templates, "_load_campaign_templates", return_value={}):
        assert prompt_templates.get_template("leads")["id"] == "leads"