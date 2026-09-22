"""
Tests for src/websocket.py.

Covers:
  - ConnectionManager: connect, disconnect, broadcast
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from src.websocket import ConnectionManager


@pytest.fixture
def manager():
    """Fresh ConnectionManager instance."""
    return ConnectionManager()


@pytest.fixture
def mock_websocket():
    """Mock WebSocket."""
    ws = MagicMock()
    ws.accept = AsyncMock()
    ws.send_json = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# connect
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_accepts_websocket(manager, mock_websocket):
    """
    Situation: New WebSocket connection.
    Expected: Accepts connection, adds to active list.
    Function: src.websocket.ConnectionManager.connect
    """
    await manager.connect(mock_websocket)
    
    mock_websocket.accept.assert_awaited_once()
    assert mock_websocket in manager.active_connections
    assert len(manager.active_connections) == 1


@pytest.mark.asyncio
async def test_connect_multiple_connections(manager, mock_websocket):
    """
    Situation: Multiple WebSocket connections.
    Expected: All added to active list.
    Function: src.websocket.ConnectionManager.connect
    """
    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()
    
    await manager.connect(mock_websocket)
    await manager.connect(ws2)
    
    assert len(manager.active_connections) == 2


# ---------------------------------------------------------------------------
# disconnect
# ---------------------------------------------------------------------------

def test_disconnect_removes_websocket(manager, mock_websocket):
    """
    Situation: WebSocket disconnects.
    Expected: Removes from active list.
    Function: src.websocket.ConnectionManager.disconnect
    """
    manager.active_connections.append(mock_websocket)
    
    manager.disconnect(mock_websocket)
    
    assert mock_websocket not in manager.active_connections
    assert len(manager.active_connections) == 0


def test_disconnect_nonexistent_websocket(manager, mock_websocket):
    """
    Situation: Disconnect WebSocket not in active list.
    Expected: Raises ValueError.
    Function: src.websocket.ConnectionManager.disconnect
    """
    with pytest.raises(ValueError):
        manager.disconnect(mock_websocket)


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_broadcast_sends_to_all_connections(manager, mock_websocket):
    """
    Situation: Broadcast message with active connections.
    Expected: Sends message to all connections.
    Function: src.websocket.ConnectionManager.broadcast
    """
    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock()
    
    manager.active_connections.append(mock_websocket)
    manager.active_connections.append(ws2)
    
    message = {"type": "test", "data": "hello"}
    await manager.broadcast(message)
    
    mock_websocket.send_json.assert_awaited_once_with(message)
    ws2.send_json.assert_awaited_once_with(message)


@pytest.mark.asyncio
async def test_broadcast_handles_send_error(manager, mock_websocket):
    """
    Situation: One connection fails to send.
    Expected: Continues broadcasting to others, logs error.
    Function: src.websocket.ConnectionManager.broadcast
    """
    ws2 = MagicMock()
    ws2.accept = AsyncMock()
    ws2.send_json = AsyncMock(side_effect=RuntimeError("send failed"))
    
    manager.active_connections.append(mock_websocket)
    manager.active_connections.append(ws2)
    
    message = {"type": "test"}
    await manager.broadcast(message)
    
    # Should still attempt to send to both
    mock_websocket.send_json.assert_awaited_once()
    ws2.send_json.assert_awaited_once()


@pytest.mark.asyncio
async def test_broadcast_empty_connections(manager):
    """
    Situation: Broadcast with no active connections.
    Expected: Does nothing, no error.
    Function: src.websocket.ConnectionManager.broadcast
    """
    message = {"type": "test"}
    await manager.broadcast(message)
    
    # Should not raise
    assert len(manager.active_connections) == 0


@pytest.mark.asyncio
async def test_broadcast_sends_dict_message(manager, mock_websocket):
    """
    Situation: Broadcast dict message.
    Expected: Sends as JSON.
    Function: src.websocket.ConnectionManager.broadcast
    """
    manager.active_connections.append(mock_websocket)
    
    message = {"type": "new_incident", "data": {"id": "INC-1"}}
    await manager.broadcast(message)
    
    mock_websocket.send_json.assert_awaited_once_with(message)
