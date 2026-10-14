from kratos_agent.output.speech_directives import DirectiveStreamFilter, extract_speech_directives


def test_marked_summary_is_spoken_without_duplicating_the_visible_answer():
    result = extract_speech_directives("I inspected the files. [[speak]]The build is ready.[[/speak]] Details are on screen.")

    assert result.display_text == "I inspected the files.  Details are on screen."
    assert result.speech_text == "The build is ready."
    assert result.valid is True


def test_unmatched_or_nested_markers_suppress_all_speech():
    unmatched = extract_speech_directives("Visible [[speak]]unfinished phrase")
    nested = extract_speech_directives("[[speak]]outer [[speak]]inner[[/speak]][[/speak]]")

    assert unmatched.speech_text == ""
    assert unmatched.valid is False
    assert nested.speech_text == ""
    assert nested.valid is False
    assert unmatched.display_text == "Visible "
    assert nested.display_text == ""


def test_stream_filter_hides_speech_body_across_split_markers():
    stream = DirectiveStreamFilter()

    output = "".join([
        stream.push("screen [[spe"),
        stream.push("ak]]spoken text[[/spe"),
        stream.push("ak]] visible"),
        stream.flush(),
    ])

    assert output == "screen  visible"


def test_streamed_reply_matches_final_display_at_every_possible_chunk_boundary():
    source = "Hey! I'm here and ready to help. [[speak]]Hi! I'm ready.[[/speak]]"
    directive = extract_speech_directives(source)
    assert directive.display_text.strip() == "Hey! I'm here and ready to help."
    assert directive.speech_text == "Hi! I'm ready."

    for boundary in range(len(source) + 1):
        stream = DirectiveStreamFilter()
        visible = stream.push(source[:boundary]) + stream.push(source[boundary:]) + stream.flush()
        assert visible == directive.display_text


def test_partial_directive_and_truncated_speech_never_leak_to_display():
    for source in ("Answer. [[spe", "Answer. [[speak]]", "Answer. [[speak]]Not yet complete"):
        assert extract_speech_directives(source).display_text.strip() == "Answer."
    assert extract_speech_directives("Answer. [[speak]]").valid is False


def test_speech_text_is_compacted_and_limited():
    result = extract_speech_directives("[[speak]]" + ("hello " * 100) + "[[/speak]]")
    assert len(result.speech_text) <= 240
    assert "\n" not in result.speech_text
