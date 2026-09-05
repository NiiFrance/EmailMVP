from unittest.mock import MagicMock, patch

import pytest

import tests.test_function_app as fixture

fa = fixture.fa


def test_extract_repair_selects_only_original_failed_indices():
    with patch.object(fa, "_download_blob", return_value=b"Name\nFirst\nSecond\nThird\n"), patch.object(
        fa, "extract_all_leads", return_value=[{"row_index": index} for index in range(3)]
    ):
        assert fa.extract_leads_activity({"job_id": "job", "row_indices": [1]}) == [{"row_index": 1}]


def test_repair_claim_blocks_existing_export():
    table = MagicMock()
    table.get_entity.return_value = {"snovioSyncOperationId": "export"}
    with patch.object(fa.data_store, "_table", return_value=table), pytest.raises(ValueError, match="export snapshot"):
        fa.data_store.claim_generation_repair("owner", "job", "repair")
    table.update_entity.assert_not_called()