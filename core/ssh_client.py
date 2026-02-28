import threading
import paramiko


class SSHClient:
    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

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
            self.disconnect_unlocked()
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                hostname=ip,
                port=port,
                username="root",
                password=password,
                timeout=timeout,
                look_for_keys=False,
                allow_agent=False,
            )
            self._client = client

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

    def upload(self, local_path, remote_path):
        with self._lock:
            if self._client is None:
                raise RuntimeError("Not connected")
            sftp = self._client.open_sftp()
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()

    def upload_string(self, content, remote_path):
        with self._lock:
            if self._client is None:
                raise RuntimeError("Not connected")
            sftp = self._client.open_sftp()
            try:
                with sftp.file(remote_path, "w") as f:
                    f.write(content)
            finally:
                sftp.close()

    def upload_bytes(self, data, remote_path):
        with self._lock:
            if self._client is None:
                raise RuntimeError("Not connected")
            sftp = self._client.open_sftp()
            try:
                with sftp.file(remote_path, "wb") as f:
                    f.write(data)
            finally:
                sftp.close()

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
