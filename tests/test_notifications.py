"""Tests for openadr3_client.notifications — MqttChannel, WebhookChannel protocol."""

from unittest.mock import MagicMock, patch

from openadr3_client.notifications import (
    MqttChannel,
    NotificationChannel,
    WebhookChannel,
)


class TestNotificationChannelProtocol:
    def test_mqtt_channel_has_protocol_methods(self):
        """MqttChannel has all NotificationChannel methods."""
        for name in ("start", "stop", "subscribe_topics", "messages", "await_messages", "clear_messages"):
            assert hasattr(MqttChannel, name), f"MqttChannel missing {name}"

    def test_webhook_channel_has_protocol_methods(self):
        """WebhookChannel has all NotificationChannel methods."""
        for name in ("start", "stop", "subscribe_topics", "messages", "await_messages", "clear_messages"):
            assert hasattr(WebhookChannel, name), f"WebhookChannel missing {name}"


class TestMqttChannel:
    @patch("openadr3_client.notifications.MQTTConnection")
    def test_start_connects(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        ch.start()
        mock_conn.connect.assert_called_once()

    @patch("openadr3_client.notifications.MQTTConnection")
    def test_stop_disconnects(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        ch.stop()
        mock_conn.disconnect.assert_called_once()

    @patch("openadr3_client.notifications.MQTTConnection")
    def test_subscribe_topics(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        ch.subscribe_topics(["topic/a", "topic/b"])
        mock_conn.subscribe.assert_called_once_with(["topic/a", "topic/b"])

    @patch("openadr3_client.notifications.MQTTConnection")
    def test_messages(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn.messages = [MagicMock()]
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        assert len(ch.messages) == 1

    @patch("openadr3_client.notifications.MQTTConnection")
    def test_clear_messages(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        ch.clear_messages()
        mock_conn.clear_messages.assert_called_once()

    @patch("openadr3_client.notifications.MQTTConnection")
    def test_is_connected(self, mock_conn_cls):
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = True
        mock_conn_cls.return_value = mock_conn

        ch = MqttChannel("mqtt://broker:1883")
        assert ch.is_connected is True


class TestWebhookChannel:
    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_start(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        ch.start()
        mock_recv.start.assert_called_once()

    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_stop(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        ch.stop()
        mock_recv.stop.assert_called_once()

    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_subscribe_topics_noop(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        ch.subscribe_topics(["topic/a"])  # Should not raise

    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_callback_url(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv.callback_url = "http://127.0.0.1:9000/notifications"
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        assert ch.callback_url == "http://127.0.0.1:9000/notifications"

    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_messages(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv.messages = [MagicMock()]
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        assert len(ch.messages) == 1

    @patch("openadr3_client.notifications.WebhookReceiver")
    def test_clear_messages(self, mock_recv_cls):
        mock_recv = MagicMock()
        mock_recv_cls.return_value = mock_recv

        ch = WebhookChannel(port=9000)
        ch.clear_messages()
        mock_recv.clear_messages.assert_called_once()
