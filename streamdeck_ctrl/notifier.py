"""Unix domain socket server for external notifications."""

import json
import logging
import os
import selectors
import socket
import threading

logger = logging.getLogger(__name__)


class Notifier:
    """Unix domain socket server that accepts notification messages.

    Runs in its own thread. Uses selectors for clean shutdown.
    Dispatches state/value updates to a callback function.
    """

    def __init__(self, socket_path, on_notification):
        """
        Args:
            socket_path: Path where the Unix domain socket will be created.
            on_notification: Callback(notification_id, state=None, value=None)
                             that returns (success: bool, error_msg: str or None).
        """
        self._socket_path = socket_path
        self._on_notification = on_notification
        self._shutdown_event = threading.Event()
        self._ready_event = threading.Event()
        self._start_error = None
        self._thread = None
        self._server_sock = None

    @property
    def socket_path(self):
        return self._socket_path

    def start(self, timeout=5):
        """Start the notifier thread and wait for socket to be ready.

        Args:
            timeout: Seconds to wait for socket bind. 0 = don't wait.

        Raises:
            RuntimeError: If the socket fails to bind within timeout.
        """
        self._thread = threading.Thread(
            target=self._run, name="notifier", daemon=True
        )
        self._thread.start()

        if timeout > 0:
            if not self._ready_event.wait(timeout=timeout):
                raise RuntimeError(
                    f"Notifier failed to start within {timeout}s: "
                    f"socket {self._socket_path}"
                )
            if self._start_error:
                raise RuntimeError(
                    f"Notifier failed to bind socket: {self._start_error}"
                )
        logger.info("Notifier started on %s", self._socket_path)

    def stop(self):
        """Stop the notifier thread and clean up the socket file."""
        self._shutdown_event.set()
        # Wake up the selector by connecting briefly
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(self._socket_path)
            s.close()
        except OSError:
            pass
        if self._thread:
            self._thread.join(timeout=5)
        self._cleanup_socket()
        logger.info("Notifier stopped")

    def _run(self):
        """Main accept loop using selectors for clean shutdown."""
        self._cleanup_socket()
        try:
            os.makedirs(os.path.dirname(self._socket_path), exist_ok=True)
            self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_sock.bind(self._socket_path)
            self._server_sock.listen(5)
            self._server_sock.setblocking(False)
        except Exception as e:
            self._start_error = str(e)
            self._ready_event.set()
            logger.error("Notifier failed to bind %s: %s", self._socket_path, e)
            return

        self._ready_event.set()

        sel = selectors.DefaultSelector()
        sel.register(self._server_sock, selectors.EVENT_READ)

        try:
            while not self._shutdown_event.is_set():
                events = sel.select(timeout=1.0)
                for key, _ in events:
                    if key.fileobj is self._server_sock:
                        self._accept_client(sel)
                    else:
                        self._handle_client(key, sel)
        except Exception:
            if not self._shutdown_event.is_set():
                logger.exception("Notifier loop error")
        finally:
            sel.close()
            self._server_sock.close()

    def _accept_client(self, sel):
        """Accept a new client connection."""
        try:
            conn, _ = self._server_sock.accept()
            conn.setblocking(False)
            # Use a mutable list as buffer since SelectorKey.data is read-only
            sel.register(conn, selectors.EVENT_READ, data=[b""])
        except OSError as e:
            logger.debug("Accept error: %s", e)

    def _handle_client(self, key, sel):
        """Read data from a client, process complete lines."""
        conn = key.fileobj
        try:
            data = conn.recv(4096)
        except OSError:
            data = b""

        if not data:
            sel.unregister(conn)
            conn.close()
            return

        buf = key.data  # mutable list
        buffer = buf[0] + data
        lines = buffer.split(b"\n")

        # Last element is incomplete data (or empty if buffer ended with \n)
        buf[0] = lines[-1]

        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            response = self._process_message(line)
            try:
                conn.sendall(json.dumps(response).encode() + b"\n")
            except OSError:
                break

    def _process_message(self, raw):
        """Parse and dispatch a single JSON message.

        Args:
            raw: bytes containing a single JSON message.

        Returns:
            dict: Response to send back to the client.
        """
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.warning("Invalid JSON from client: %s", e)
            return {"status": "error", "reason": f"invalid JSON: {e}"}

        nid = msg.get("id")
        if not nid:
            return {"status": "error", "reason": "missing 'id' field"}

        state = msg.get("state")
        value = msg.get("value")

        if state is None and value is None:
            return {"status": "error", "reason": "message must include 'state' or 'value'"}

        ok, err = self._on_notification(nid, state=state, value=value)
        if ok:
            return {"status": "ok"}
        else:
            return {"status": "error", "reason": err}

    def _cleanup_socket(self):
        """Remove stale socket file."""
        try:
            os.unlink(self._socket_path)
        except OSError:
            pass
