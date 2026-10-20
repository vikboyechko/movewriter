import threading
import logging
import paramiko

log = logging.getLogger(__name__)


class SSHClient:
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()
        # Saved credentials for transparent reconnect. xochitl stop/start
        # can bounce the USB network on newer firmware; operations then
        # retry once on a fresh connection.
        self._last_ip = None
        self._last_password = None
        self._last_port = 22

    @property
    def is_connected(self):
        # No lock — safe to read transport status without blocking the main thread
        client = self._client
        if client is None:
            return False
        try:
            transport = client.get_transport()
            return transport is not None and transport.is_active()
        except Exception:
            return False

    def connect(self, ip, password, port=22, timeout=10):
        with self._lock:
            self._last_ip = ip
            self._last_password = password
            self._last_port = port
            self._connect_unlocked(ip, password, port, timeout)

    def _connect_unlocked(self, ip, password, port, timeout=10):
        self.disconnect_unlocked()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if password:
            client.connect(
                hostname=ip,
                port=port,
                username="root",
                password=password,
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
        else:
            client.connect(
                hostname=ip,
                port=port,
                username="root",
                timeout=timeout,
                look_for_keys=True,
                allow_agent=True,
            )
        self._client = client

    def _reconnect_unlocked(self):
        """Reconnect using saved credentials. Returns True on success."""
        if self._last_ip is None:
            return False
        log.info("SSH connection lost — reconnecting to %s", self._last_ip)
        try:
            self._connect_unlocked(self._last_ip, self._last_password,
                                   self._last_port)
            return True
        except Exception as e:
            log.warning("SSH reconnect failed: %s", e)
            return False

    def disconnect(self):
        with self._lock:
            self.disconnect_unlocked()

    def disconnect_unlocked(self):
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass
            self._client = None

    def exec(self, cmd, timeout=30):
        with self._lock:
            if self._client is None:
                raise RuntimeError("Not connected")
            try:
                return self._exec_unlocked(cmd, timeout)
            except Exception:
                if not self._reconnect_unlocked():
                    raise
                return self._exec_unlocked(cmd, timeout)

    def _exec_unlocked(self, cmd, timeout=30):
        stdin, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
        # recv_exit_status() blocks forever if the command hangs,
        # so use the channel's event with a timeout instead
        channel = stdout.channel
        if not channel.status_event.wait(timeout=timeout):
            channel.close()
            raise TimeoutError(f"Command timed out after {timeout}s: {cmd}")
        exit_code = channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return out, err, exit_code

    def _sftp_call(self, fn):
        """Run an SFTP operation, reconnecting once if the transport died
        mid-operation."""
        with self._lock:
            if self._client is None:
                raise RuntimeError("Not connected")
            try:
                return fn(self._client.open_sftp())
            except Exception:
                if not self._reconnect_unlocked():
                    raise
                return fn(self._client.open_sftp())

    def upload(self, local_path, remote_path):
        def op(sftp):
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()
        self._sftp_call(op)

    def upload_string(self, content, remote_path):
        def op(sftp):
            try:
                with sftp.file(remote_path, "w") as f:
                    f.write(content)
            finally:
                sftp.close()
        self._sftp_call(op)

    def download_bytes(self, remote_path):
        def op(sftp):
            try:
                with sftp.file(remote_path, "rb") as f:
                    return f.read()
            finally:
                sftp.close()
        return self._sftp_call(op)

    def upload_bytes(self, data, remote_path):
        def op(sftp):
            try:
                with sftp.file(remote_path, "wb") as f:
                    f.write(data)
            finally:
                sftp.close()
        self._sftp_call(op)

    def open_channel(self):
        """Open a Paramiko channel with a PTY for interactive sessions.

        Does NOT acquire self._lock — transport is thread-safe for opening
        channels. Caller is responsible for closing the channel.
        """
        client = self._client
        if client is None:
            raise RuntimeError("Not connected")
        transport = client.get_transport()
        if transport is None or not transport.is_active():
            raise RuntimeError("Not connected")
        channel = transport.open_session()
        channel.get_pty(term="dumb", width=200, height=50)
        channel.invoke_shell()
        return channel

    def run_in_background(self, cmd, callback, timeout=60):
        def worker():
            try:
                result = self.exec(cmd, timeout=timeout)
                callback(result, None)
            except Exception as e:
                callback(None, e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        return t
