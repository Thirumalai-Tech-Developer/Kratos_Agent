from kratos_agent.output.speech_directives import DirectiveStreamFilter, extract_speech_directives


def test_only_marked_text_is_speech_and_markers_are_removed_from_display():
    result = extract_speech_directives("I inspected the files. [[speak]]The build is ready.[[/speak]] Details are on screen.")

    assert result.display_text == "I inspected the files. The build is ready. Details are on screen."
    assert result.speech_text == "The build is ready."
    assert result.valid is True


def test_unmatched_or_nested_markers_suppress_all_speech():
    unmatched = extract_speech_directives("Visible [[speak]]unfinished phrase")
    nested = extract_speech_directives("[[speak]]outer [[speak]]inner[[/speak]][[/speak]]")

    assert unmatched.speech_text == ""
    assert unmatched.valid is False
    assert nested.speech_text == ""
    assert nested.valid is False


def test_stream_filter_removes_markers_split_across_chunks():
    stream = DirectiveStreamFilter()

    output = "".join([
        stream.push("screen [[spe"),
        stream.push("ak]]spoken text[[/spe"),
        stream.push("ak]] visible"),
        stream.flush(),
    ])

    assert output == "screen spoken text visible"


def test_speech_text_is_compacted_and_limited():
    result = extract_speech_directives("[[speak]]" + ("hello " * 100) + "[[/speak]]")
    assert len(result.speech_text) <= 240
    assert "\n" not in result.speech_text
