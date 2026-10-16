async def test_unknown_user_gets_no_reply_and_is_stored_as_not_allowed(harness, make_uow):
    await harness.send_text("hello", user_id=7, first_name="Eve", username="eve")

    assert harness.session.calls == []
    async with make_uow() as uow:
        user = await uow.users.get(7)
    assert user is not None
    assert (user.username, user.first_name, user.is_allowed) == ("eve", "Eve", False)


async def test_allowed_user_gets_exactly_one_greeting_with_their_name(harness, allow_user):
    await allow_user(7, first_name="Ann")

    await harness.send_text("/start", user_id=7, first_name="Ann")

    assert len(harness.session.calls) == 1
    (sent,) = harness.sent_messages
    assert sent.chat_id == 7
    assert "Ann" in sent.text


async def test_greeting_escapes_html_in_the_name(harness, allow_user):
    await allow_user(7, first_name="<b>Ann")

    await harness.send_text("/start", user_id=7, first_name="<b>Ann")

    (sent,) = harness.sent_messages
    assert "&lt;b&gt;Ann" in sent.text


async def test_changed_username_is_stored(harness, allow_user, make_uow):
    await allow_user(7, username="old")

    await harness.send_text("/start", user_id=7, username="new")

    async with make_uow() as uow:
        user = await uow.users.get(7)
    assert user.username == "new"


async def test_not_allowed_user_sending_start_gets_no_reply(harness, make_uow):
    await harness.send_text("/start", user_id=7)

    assert harness.session.calls == []
    async with make_uow() as uow:
        assert (await uow.users.get(7)) is not None
