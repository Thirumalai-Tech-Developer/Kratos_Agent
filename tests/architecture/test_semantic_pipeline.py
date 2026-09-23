from kratos_agent.semantic.intent import mission_from_tool_call


def test_question_shaped_request_is_preserved_as_one_mission():
    intent = mission_from_tool_call(
        {
            "mission": "can you play rakama kaiyathattu in youtube",
            "capability": "browser.youtube.play",
            "arguments": {"query": "rakama kaiyathattu"},
            "expected_state": {"video_playing": True},
        }
    )
    assert intent.goal == "can you play rakama kaiyathattu in youtube"
    assert intent.capability == "browser.youtube.play"
    assert intent.arguments["query"] == "rakama kaiyathattu"


def test_same_interface_contract_has_no_phrase_specific_fields():
    intent = mission_from_tool_call({"mission": "open whatsapp and send hi to thirumalai"})
    assert intent.capability is None
    assert intent.arguments == {}
