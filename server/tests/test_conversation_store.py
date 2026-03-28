import pytest

from app.services.conversation_store import ConversationStore

pytestmark = pytest.mark.no_model


class TestGetOrCreate:
    def test_new_conversation(self, fresh_conversation_store):
        conv_id = fresh_conversation_store.get_or_create()
        assert conv_id
        assert isinstance(conv_id, str)

    def test_specific_id(self, fresh_conversation_store):
        conv_id = fresh_conversation_store.get_or_create("my-convo-123")
        assert conv_id == "my-convo-123"

    def test_existing_id_returns_same(self, fresh_conversation_store):
        store = fresh_conversation_store
        conv_id = store.get_or_create("existing-id")
        same_id = store.get_or_create("existing-id")
        assert same_id == conv_id


class TestGetHistory:
    def test_empty_history(self, fresh_conversation_store):
        conv_id = fresh_conversation_store.get_or_create()
        history = fresh_conversation_store.get_history(conv_id)
        assert history == []

    def test_nonexistent_returns_empty(self, fresh_conversation_store):
        history = fresh_conversation_store.get_history("does-not-exist")
        assert history == []


class TestAddMessage:
    def test_user_and_assistant(self, fresh_conversation_store):
        store = fresh_conversation_store
        conv_id = store.get_or_create()
        store.add_message(conv_id, "user", "Hello")
        store.add_message(conv_id, "assistant", "Hi there!")
        history = store.get_history(conv_id)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "Hello"}
        assert history[1] == {"role": "assistant", "content": "Hi there!"}

    def test_trim_at_max_history(self):
        store = ConversationStore(max_history=4)
        conv_id = store.get_or_create()
        for i in range(6):
            store.add_message(conv_id, "user", f"msg-{i}")
        history = store.get_history(conv_id)
        assert len(history) == 4
        assert history[0]["content"] == "msg-2"

    def test_preview_from_first_user_message(self, fresh_conversation_store):
        store = fresh_conversation_store
        conv_id = store.get_or_create()
        store.add_message(conv_id, "user", "What is quantum physics?")
        store.add_message(conv_id, "assistant", "It is a branch of physics.")
        convos = store.list_conversations()
        match = [c for c in convos if c["id"] == conv_id][0]
        assert match["preview"] == "What is quantum physics?"


class TestListConversations:
    def test_empty(self, fresh_conversation_store):
        assert fresh_conversation_store.list_conversations() == []

    def test_multiple(self, fresh_conversation_store):
        store = fresh_conversation_store
        store.get_or_create("a")
        store.get_or_create("b")
        convos = store.list_conversations()
        assert len(convos) == 2

    def test_newest_first(self, fresh_conversation_store):
        store = fresh_conversation_store
        store.get_or_create("first")
        store.get_or_create("second")
        convos = store.list_conversations()
        # second was created after first, should appear first
        assert convos[0]["id"] == "second"


class TestDeleteConversation:
    def test_existing_returns_true(self, fresh_conversation_store):
        store = fresh_conversation_store
        conv_id = store.get_or_create()
        assert store.delete_conversation(conv_id) is True

    def test_nonexistent_returns_false(self, fresh_conversation_store):
        assert fresh_conversation_store.delete_conversation("nope") is False
