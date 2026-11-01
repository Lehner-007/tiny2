"""Bounded MCP stdio client. No shell, package install, or network discovery."""
from pathlib import Path
import json
import os
import queue
import shutil
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parents[1]

class BackendError(RuntimeError):
    pass


def node_command():
    bundled = ROOT / 'runtime' / 'node' / 'bin' / 'node'
    if bundled.is_file():
        return str(bundled)
    return os.environ.get('OBSBOT_NODE') or shutil.which('node') or 'node'


class Backend:
    def __init__(self, logger=None, command=None, runtime_dir=None):
        self.logger = logger
        self.runtime_dir = Path(runtime_dir) if runtime_dir is not None else ROOT/'.config/ipc'
        self.command = command
        self.process = None
        self.responses = queue.Queue()
        self.lock = threading.Lock()
        self.counter = 0
        self.closed = False

    def start(self):
        if self.closed:
            raise BackendError('backend_closed')
        if self.process and self.process.poll() is None:
            return
        if self.command is None:
            if not (ROOT / 'dist/index.js').is_file():
                raise BackendError('backend_missing')
            if not (ROOT / 'native/prebuilt/linux-x64/obsbot-helper').is_file():
                raise BackendError('helper_missing')
        runtime = self.runtime_dir
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        runtime.chmod(0o700)
        env = dict(os.environ, OBSBOT_IPC_DIR=str(runtime), OBSBOT_IPC_NAME='obsbot-desktop',
                   OBSBOT_TAIL2_HOSTS='', OBSBOT_TAIL2_MDNS='0')
        self.responses = queue.Queue()
        try:
            self.process = subprocess.Popen(self.command or [node_command(), str(ROOT/'dist/index.js')],
                cwd=ROOT, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1)
        except OSError as exc:
            raise BackendError('node_missing') from exc
        threading.Thread(target=self._read, args=(self.process,self.responses), daemon=True).start()
        threading.Thread(target=self._errors, args=(self.process,), daemon=True).start()
        self.request('initialize', {'protocolVersion':'2024-11-05',
            'capabilities':{},'clientInfo':{'name':'obsbot-desktop','version':(ROOT/'VERSION').read_text().strip()}}, start=False)
        self._write({'jsonrpc':'2.0','method':'notifications/initialized'})

    def _read(self, process, responses):
        for line in process.stdout:
            try:
                message = json.loads(line)
                if 'id' in message:
                    responses.put(message)
            except (ValueError, TypeError):
                responses.put({'error':{'message':'invalid_backend_reply'}})
        responses.put({'error':{'message':'backend_exited'}})

    def _errors(self, process):
        for line in process.stderr:
            if self.logger:
                self.logger.info('MCP: %s', line.rstrip()[:2000])

    def _write(self, message):
        if not self.process or self.process.poll() is not None:
            raise BackendError('backend_exited')
        try:
            self.process.stdin.write(json.dumps(message)+'\n')
            self.process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise BackendError('backend_exited') from exc

    def request(self, method, params=None, *, timeout=35, start=True):
        if start:
            self.start()
        with self.lock:
            self.counter += 1
            identifier = self.counter
            self._write({'jsonrpc':'2.0','id':identifier,'method':method,'params':params or {}})
            try:
                message = self.responses.get(timeout=timeout)
            except queue.Empty as exc:
                self._stop_process()
                raise BackendError('backend_timeout') from exc
            if 'error' in message:
                raise BackendError(message['error'].get('message','backend_error'))
            if message.get('id') != identifier:
                self._stop_process()
                raise BackendError('invalid_backend_reply')
            return message.get('result',{})

    def tools(self):
        return [tool for tool in self.request('tools/list')['tools']
                if tool['name'].startswith('obsbot_') and not tool['name'].startswith('obsbot_tail2_')]

    def call(self, name, arguments=None):
        result = self.request('tools/call', {'name':name,'arguments':arguments or {}})
        texts = [part['text'] for part in result.get('content',[]) if part.get('type')=='text']
        if result.get('isError'):
            raise BackendError('\n'.join(texts))
        value = None
        for text in texts:
            try:
                value = json.loads(text)
            except ValueError:
                raise BackendError(text)
        if isinstance(value,dict) and value.get('ok') is False:
            raise BackendError(str(value.get('reason') or value.get('error') or value))
        return value if value is not None else result

    def wake_verified(self,camera=None,timeout=5):
        arguments={'camera':camera} if camera else {}
        self.call('obsbot_wake',arguments)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=self.call('obsbot_status',arguments)
            if isinstance(status,dict) and status.get('awake') is True:
                return {'ok':True,'awake':True,'verified':True}
            time.sleep(.15)
        raise BackendError('wake_not_confirmed')

    def sleep_verified(self,camera,timeout=6):
        arguments={'camera':camera}
        self.call('obsbot_sleep',arguments)
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            status=self.call('obsbot_status',arguments)
            if isinstance(status,dict) and status.get('awake') is False:return True
            time.sleep(.2)
        raise BackendError('sleep_not_confirmed')

    def _stop_process(self):
        process, self.process = self.process, None
        if process is None:
            return
        if process.poll() is None:
            try:
                process.stdin.close()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=2)
        for stream in (process.stdout, process.stderr):
            if stream:
                stream.close()

    def close(self):
        self.closed = True
        self._stop_process()
