from unittest.mock import MagicMock

import pytest

import tests.test_function_app as fixture


@pytest.mark.parametrize("repair", [False, True])
def test_orchestration_reaches_assembly_and_returns_counts(repair):
    context = MagicMock()
    context.get_input.return_value = {"job_id": "job", "repair": repair, "row_indices": [1], "total_leads": 3}
    generator = fixture.fa.orchestrate_emails(context)
    next(generator)
    extract = context.call_activity.call_args.args[1]
    assert (extract.get("row_indices") == [1]) is repair
    generator.send([{"row_index": 1}])
    generator.send([{"row_index": 1, "parsed": [{"subject": "Hello", "body": "Body"}]}])
    assembly = context.call_activity.call_args.args[1]
    assert bool(assembly.get("preserve_existing")) is repair
    with pytest.raises(StopIteration) as ended:
        generator.send("output.csv")
    assert ended.value.value["status"] == "completed"
    assert ended.value.value["totalLeads"] == (3 if repair else 1)