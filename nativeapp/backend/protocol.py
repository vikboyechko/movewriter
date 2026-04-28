"""AppLoad socket protocol handler.

AppLoad sends header and payload as SEPARATE SEQPACKET messages:
  recv() #1: 8-byte header (u32 msg_type + u32 length)
  recv() #2: payload bytes (length from header)

System messages (NEW_FRONTEND, TERMINATE) have a 1-byte payload
sent as a separate message that should be consumed.
"""
import json
import logging
import socket
import struct
import threading

log = logging.getLogger(__name__)

MSG_REQUEST = 1
MSG_RESPONSE = 2
MSG_EVENT = 3

SYS_TERMINATE = 0xFFFFFFFF
SYS_NEW_FRONTEND = 0xFFFFFFFE

HEADER_SIZE = 8
HEADER_FMT = '<II'


class Protocol:
    def __init__(self, socket_path):
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self._sock.connect(socket_path)
        self._send_lock = threading.Lock()

    def recv(self):
        """Receive a message. Returns (msg_type, payload_dict_or_None)."""
        # Read header (8 bytes)
        header = self._sock.recv(65536)
        if not header:
            raise ConnectionError("Socket closed")

        if len(header) < HEADER_SIZE:
            # Consume stray payload from previous system message
            log.debug("Skipping short message: %d bytes", len(header))
            # Try to read the next real header
            header = self._sock.recv(65536)
            if not header or len(header) < HEADER_SIZE:
                raise ConnectionError("Socket closed or invalid")

        msg_type, length = struct.unpack(HEADER_FMT, header[:HEADER_SIZE])

        # System messages — consume their payload
        if msg_type >= SYS_NEW_FRONTEND:
            if length > 0:
                try:
                    self._sock.recv(65536)  # consume payload
                except Exception:
                    pass
            return msg_type, None

        # App message — read payload as separate message
        if length > 0:
            payload_data = self._sock.recv(65536)
            if payload_data:
                try:
                    return msg_type, json.loads(payload_data.decode('utf-8'))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    log.error("Failed to parse payload: %s", e)
                    return msg_type, None
        return msg_type, {}

    def send(self, msg_type, payload):
        """Send a message as two SEQPACKET messages: header then payload."""
        body = json.dumps(payload).encode('utf-8')
        header = struct.pack(HEADER_FMT, msg_type, len(body))
        with self._send_lock:
            self._sock.send(header)
            if body:
                self._sock.send(body)

    def send_response(self, payload):
        self.send(MSG_RESPONSE, payload)

    def send_event(self, payload):
        self.send(MSG_EVENT, payload)

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass
