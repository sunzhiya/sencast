import base64
import http.server
import json
import os
import re
import socketserver
import threading
import time
import urllib.parse
import urllib.request
import uuid as _uuid
from xml.sax.saxutils import escape

from . import device
from . import services
from . import ssdp

ICON_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==')

UPLOAD_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>发送到电脑 · 森投屏</title>
<style>
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;min-height:100%}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;
background:radial-gradient(120% 90% at 50% 0%,#1d2333 0%,#0d1017 55%,#080a0e 100%);
color:#eef1f7;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:22px}
.card{width:100%;max-width:430px;background:rgba(255,255,255,.055);border:1px solid rgba(255,255,255,.10);
border-radius:28px;padding:26px 22px 24px;backdrop-filter:blur(22px);box-shadow:0 24px 70px rgba(0,0,0,.55)}
.logo{width:58px;height:58px;border-radius:19px;margin:0 auto 14px;background:linear-gradient(145deg,#4cc9ff,#6f7bff);
display:flex;align-items:center;justify-content:center;font-size:27px;font-weight:800;color:#fff;
box-shadow:0 10px 26px rgba(90,140,255,.45)}
h1{font-size:20px;margin:0 0 6px;text-align:center;letter-spacing:.5px}
.sub{text-align:center;font-size:12px;color:#9aa3b5;margin:0 0 22px}
.pick{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;padding:15px;border-radius:999px;
background:linear-gradient(135deg,#4cc9ff,#6f7bff);color:#fff;font-size:15px;font-weight:700;letter-spacing:.5px;
box-shadow:0 12px 30px rgba(80,130,255,.42);cursor:pointer;transition:transform .15s ease,box-shadow .15s ease}
.pick:active{transform:scale(.97);box-shadow:0 6px 18px rgba(80,130,255,.35)}
#list{margin-top:20px;display:flex;flex-direction:column;gap:12px}
.row{background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.08);border-radius:16px;padding:12px 14px}
.nm{font-size:13px;color:#e6eaf3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bar{height:6px;border-radius:999px;background:rgba(255,255,255,.14);margin:9px 0 6px;overflow:hidden}
.bar i{display:block;height:100%;width:0;border-radius:999px;background:linear-gradient(90deg,#4cc9ff,#6f7bff);transition:width .15s ease}
.pc{font-size:11px;color:#9aa3b5;text-align:right}
.row.ok{border-color:rgba(60,220,140,.45)}
.row.ok .pc{color:#4ee39a}
.row.err{border-color:rgba(255,90,110,.5)}
.row.err .pc{color:#ff6b7d}
</style>
</head>
<body>
<div class="card">
  <div class="logo">森</div>
  <h1>发送到电脑</h1>
  <p class="sub">同一 Wi-Fi 直连 · 不经过任何服务器</p>
  <label class="pick"><input id="f" type="file" multiple hidden>选择文件发送</label>
  <div id="list"></div>
</div>
<script>
var input=document.getElementById('f'),list=document.getElementById('list');
var queue=[],busy=false;
input.addEventListener('change',function(){for(var i=0;i<input.files.length;i++){queue.push(input.files[i]);}input.value='';pump();});
function pump(){if(busy||!queue.length)return;busy=true;upload(queue.shift());}
function upload(file){
  var row=document.createElement('div');row.className='row';
  var nm=document.createElement('div');nm.className='nm';nm.textContent=file.name;
  var bar=document.createElement('div');bar.className='bar';var fill=document.createElement('i');bar.appendChild(fill);
  var pc=document.createElement('div');pc.className='pc';pc.textContent='准备中…';
  row.appendChild(nm);row.appendChild(bar);row.appendChild(pc);list.appendChild(row);
  var xhr=new XMLHttpRequest();
  xhr.open('POST','/upload?name='+encodeURIComponent(file.name));
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=function(e){
    if(!e.lengthComputable)return;
    var p=Math.round(e.loaded*100/e.total);
    fill.style.width=p+'%';pc.textContent=p+'%';
  };
  xhr.onload=function(){
    if(xhr.status===200){fill.style.width='100%';pc.textContent='完成 ✓';row.classList.add('ok');}
    else{pc.textContent='失败 ('+xhr.status+')';row.classList.add('err');}
    busy=false;pump();
  };
  xhr.onerror=function(){pc.textContent='失败：网络中断';row.classList.add('err');busy=false;pump();};
  xhr.send(file);
}
</script>
</body>
</html>"""

SERVICE_SPECS = {
    'ConnectionManager': {
        'actions': [
            ('GetProtocolInfo', [('Source', 'out', 'SourceProtocolInfo'),
                                 ('Sink', 'out', 'SinkProtocolInfo')]),
            ('GetCurrentConnectionIDs', [('ConnectionIDs', 'out', 'CurrentConnectionIDs')]),
            ('GetCurrentConnectionInfo',
             [('ConnectionID', 'in', 'A_ARG_TYPE_ConnectionID'),
              ('RcsID', 'out', 'A_ARG_TYPE_RcsID'),
              ('AVTransportID', 'out', 'A_ARG_TYPE_AVTransportID'),
              ('ProtocolInfo', 'out', 'A_ARG_TYPE_ProtocolInfo'),
              ('PeerConnectionManager', 'out', 'A_ARG_TYPE_ConnectionManager'),
              ('PeerConnectionID', 'out', 'A_ARG_TYPE_ConnectionID'),
              ('Direction', 'out', 'A_ARG_TYPE_Direction'),
              ('Status', 'out', 'A_ARG_TYPE_ConnectionStatus')]),
        ],
        'state_vars': [('SourceProtocolInfo', 'string'), ('SinkProtocolInfo', 'string'),
                       ('CurrentConnectionIDs', 'string'),
                       ('A_ARG_TYPE_ConnectionID', 'i4'), ('A_ARG_TYPE_RcsID', 'i4'),
                       ('A_ARG_TYPE_AVTransportID', 'i4'),
                       ('A_ARG_TYPE_ProtocolInfo', 'string'),
                       ('A_ARG_TYPE_ConnectionManager', 'string'),
                       ('A_ARG_TYPE_Direction', 'string'),
                       ('A_ARG_TYPE_ConnectionStatus', 'string')],
    },
    'AVTransport': {
        'actions': [
            ('SetAVTransportURI', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                   ('CurrentURI', 'in', 'AVTransportURI'),
                                   ('CurrentURIMetaData', 'in', 'AVTransportURIMetaData')]),
            ('Play', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                      ('Speed', 'in', 'TransportPlaySpeed')]),
            ('Pause', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID')]),
            ('Stop', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID')]),
            ('Seek', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                      ('Unit', 'in', 'A_ARG_TYPE_SeekMode'),
                      ('Target', 'in', 'A_ARG_TYPE_SeekTarget')]),
            ('SetPlayMode', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('NewPlayMode', 'in', 'CurrentPlayMode')]),
            ('GetTransportInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                  ('CurrentTransportState', 'out', 'TransportState'),
                                  ('CurrentTransportStatus', 'out', 'TransportStatus'),
                                  ('CurrentSpeed', 'out', 'TransportPlaySpeed')]),
            ('GetPositionInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                 ('Track', 'out', 'CurrentTrack'),
                                 ('TrackDuration', 'out', 'CurrentTrackDuration'),
                                 ('TrackMetaData', 'out', 'CurrentTrackMetaData'),
                                 ('TrackURI', 'out', 'CurrentTrackURI'),
                                 ('RelTime', 'out', 'RelativeTimePosition'),
                                 ('AbsTime', 'out', 'AbsoluteTimePosition'),
                                 ('RelCount', 'out', 'RelativeCounterPosition'),
                                 ('AbsCount', 'out', 'AbsoluteCounterPosition')]),
            ('GetMediaInfo', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                              ('NrTracks', 'out', 'NumberOfTracks'),
                              ('MediaDuration', 'out', 'CurrentMediaDuration'),
                              ('CurrentURI', 'out', 'AVTransportURI'),
                              ('CurrentURIMetaData', 'out', 'AVTransportURIMetaData'),
                              ('NextURI', 'out', 'NextAVTransportURI'),
                              ('NextURIMetaData', 'out', 'NextAVTransportURIMetaData'),
                              ('PlayMedium', 'out', 'PlaybackStorageMedium'),
                              ('RecordMedium', 'out', 'RecordStorageMedium'),
                              ('WriteStatus', 'out', 'RecordMediumWriteStatus')]),
            ('GetDeviceCapabilities', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                       ('PlayMedia', 'out', 'PossiblePlaybackStorageMedia'),
                                       ('RecMedia', 'out', 'PossibleRecordStorageMedia'),
                                       ('RecQualityModes', 'out', 'PossibleRecordQualityModes')]),
            ('GetTransportSettings', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                                      ('PlayMode', 'out', 'CurrentPlayMode'),
                                      ('RecQualityMode', 'out', 'CurrentRecordQualityMode')]),
        ],
        'state_vars': [('TransportState', 'string'), ('TransportStatus', 'string'),
                       ('TransportPlaySpeed', 'string'), ('CurrentPlayMode', 'string'),
                       ('CurrentRecordQualityMode', 'string'), ('NumberOfTracks', 'ui4'),
                       ('CurrentTrack', 'ui4'), ('CurrentTrackDuration', 'string'),
                       ('CurrentMediaDuration', 'string'), ('CurrentTrackMetaData', 'string'),
                       ('CurrentTrackURI', 'string'), ('AVTransportURI', 'string'),
                       ('AVTransportURIMetaData', 'string'), ('NextAVTransportURI', 'string'),
                       ('NextAVTransportURIMetaData', 'string'),
                       ('RelativeTimePosition', 'string'), ('AbsoluteTimePosition', 'string'),
                       ('RelativeCounterPosition', 'i4'), ('AbsoluteCounterPosition', 'i4'),
                       ('PlaybackStorageMedium', 'string'), ('RecordStorageMedium', 'string'),
                       ('RecordMediumWriteStatus', 'string'),
                       ('PossiblePlaybackStorageMedia', 'string'),
                       ('PossibleRecordStorageMedia', 'string'),
                       ('PossibleRecordQualityModes', 'string'),
                       ('A_ARG_TYPE_InstanceID', 'ui4'), ('A_ARG_TYPE_SeekMode', 'string'),
                       ('A_ARG_TYPE_SeekTarget', 'string')],
    },
    'RenderingControl': {
        'actions': [
            ('GetVolume', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                           ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                           ('CurrentVolume', 'out', 'Volume')]),
            ('SetVolume', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                           ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                           ('DesiredVolume', 'in', 'Volume')]),
            ('GetMute', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                         ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                         ('CurrentMute', 'out', 'Mute')]),
            ('SetMute', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                         ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                         ('DesiredMute', 'in', 'Mute')]),
            ('GetVolumeDB', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                             ('CurrentVolume', 'out', 'VolumeDB')]),
            ('SetVolumeDB', [('InstanceID', 'in', 'A_ARG_TYPE_InstanceID'),
                             ('Channel', 'in', 'A_ARG_TYPE_Channel'),
                             ('DesiredVolume', 'in', 'VolumeDB')]),
        ],
        'state_vars': [('Volume', 'ui2'), ('Mute', 'boolean'), ('VolumeDB', 'i2'),
                       ('A_ARG_TYPE_InstanceID', 'ui4'), ('A_ARG_TYPE_Channel', 'string')],
    },
}


def _build_scpd(service):
    spec = SERVICE_SPECS[service]
    actions = []
    for name, args in spec['actions']:
        if args:
            arg_xml = ''.join(
                '<argument><name>%s</name><direction>%s</direction>'
                '<relatedStateVariable>%s</relatedStateVariable></argument>'
                % (n, d, sv) for n, d, sv in args)
            actions.append('<action><name>%s</name><argumentList>%s</argumentList></action>'
                           % (name, arg_xml))
        else:
            actions.append('<action><name>%s</name><argumentList/></action>' % name)
    state_vars = ''.join(
        '<stateVariable sendEvents="no"><name>%s</name><dataType>%s</dataType></stateVariable>'
        % (n, t) for n, t in spec['state_vars'])
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<scpd xmlns="urn:schemas-upnp-org:service-1-0">'
            '<specVersion><major>1</major><minor>0</minor></specVersion>'
            '<actionList>%s</actionList>'
            '<serviceStateTable>%s</serviceStateTable>'
            '</scpd>' % (''.join(actions), state_vars))


SCPD = {svc: _build_scpd(svc) for svc in SERVICE_SPECS}


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            ip = self.client_address[0] if self.client_address else '?'
            self.server.log('[HTTP] %s %s' % (ip, fmt % args))
        except Exception:
            pass

    def _send(self, code, body, content_type='text/xml; charset="utf-8"', extra=None):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Server', 'SenAICastReceiver/1.0')
        self.send_header('Cache-Control', 'no-cache')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def do_GET(self):
        ip = self.client_address[0] if self.client_address else '?'
        ua = self.headers.get('User-Agent', '') if self.headers else ''
        try:
            self.server.state.detect_control_point(ua)
        except Exception:
            pass
        if self.path in ('/', '/index.html', '/send'):
            self._send(200, UPLOAD_HTML, content_type='text/html; charset="utf-8"')
            return
        if self.path == '/device.xml':
            self.server.log('[HTTP] %s GET /device.xml (User-Agent: %s)' % (ip, ua))
            if not getattr(self.server, '_diag_http_dumped', False):
                self.server._diag_http_dumped = True
                hdr = '\n'.join('%s: %s' % (k, v) for k, v in self.headers.items())
                self.server.log('[HTTP][诊断] /device.xml 完整请求头:\n%s' % hdr)
            self._send(200, device.device_description(
                self.server.app_ip, self.server.app_port, self.server.app_name,
                tv_mode=getattr(self.server, 'tv_mode', False)))
            return
        if self.path.startswith('/upnp/scpd/'):
            for key, xml in SCPD.items():
                if key in self.path:
                    self._send(200, xml)
                    return
            self._send(404, '<error>no scpd</error>')
            return
        if self.path == '/icon.png':
            self._send(200, ICON_PNG, content_type='image/png')
            return
        self._send(404, '<error>not found</error>')

    def do_POST(self):
        if self.path.startswith('/upload'):
            self._handle_upload()
            return
        length = int(self.headers.get('Content-Length', 0) or 0)
        body = self.rfile.read(length) if length else b''
        if self.path.startswith('/upnp/control/'):
            try:
                if self.server.state.detect_control_point(
                        self.headers.get('User-Agent', '')):
                    self.server.log(
                        '[兼容] 识别控制点: %s -> %s'
                        % (self.server.state.control_point,
                           '标准状态机(含 TRANSITIONING)'
                           if self.server.state.use_transitioning
                           else '三态(STOPPED/PLAYING/PAUSED_PLAYBACK)'))
            except Exception:
                pass
            action, params = services.parse_soap(body)
            if action is None:
                self._send(500, services._soap_fault('Client', 'Bad SOAP'), extra={'EXT': ''})
                return
            code, resp, _ = self.server.state.handle(self.path, action, params)
            self._send(code, resp, extra={'EXT': ''})
            summary = params.get('CurrentURI', '')[:90]
            self.server.log('[DLNA] 收到指令 %s %s' % (action, summary))
            return
        self._send(404, '<error>not found</error>')

    def _handle_upload(self):
        ip = self.client_address[0] if self.client_address else '?'
        try:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        except Exception:
            q = {}
        raw = (q.get('name') or ['upload.bin'])[0]
        name = os.path.basename(str(raw).replace('\\', '/')) or 'upload.bin'
        try:
            total = int(self.headers.get('Content-Length', 0) or 0)
        except Exception:
            total = 0
        dest_dir = getattr(self.server, 'upload_dir', None) or os.path.join(
            os.path.expanduser('~'), 'Downloads', '\u68ee\u6295\u5c4f\u63a5\u6536')
        try:
            os.makedirs(dest_dir, exist_ok=True)
        except Exception:
            pass
        dest = self._unique_path(dest_dir, name)
        tmp = dest + '.part'
        recv = 0
        t0 = time.time()
        last_emit = 0.0
        cb = getattr(self.server, 'upload_progress_cb', None)
        done_cb = getattr(self.server, 'upload_done_cb', None)
        try:
            self.server.log('[文件] 开始接收 %s (%d bytes) <- %s'
                            % (name, total, ip))
        except Exception:
            pass
        if cb:
            try:
                cb(name, 0, '')
            except Exception:
                pass
        ok = False
        try:
            with open(tmp, 'wb') as f:
                while recv < total:
                    chunk = self.rfile.read(min(65536, total - recv))
                    if not chunk:
                        break
                    f.write(chunk)
                    recv += len(chunk)
                    now = time.time()
                    if now - last_emit >= 0.25 or recv >= total:
                        last_emit = now
                        elapsed = max(0.001, now - t0)
                        pct = int(recv * 100 / total) if total else 100
                        if cb:
                            try:
                                cb(name, pct, self._fmt_speed(recv / elapsed))
                            except Exception:
                                pass
            os.replace(tmp, dest)
            ok = True
        except Exception as e:
            try:
                self.server.log('[文件] 接收失败 %s: %s' % (name, e))
            except Exception:
                pass
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass
        if ok:
            try:
                self.server.log('[文件] 已保存 %s -> %s' % (name, dest))
            except Exception:
                pass
            if done_cb:
                try:
                    done_cb(name, dest)
                except Exception:
                    pass
            self._send(200, json.dumps({'ok': True,
                                        'name': os.path.basename(dest),
                                        'path': dest}),
                       content_type='application/json; charset="utf-8"')
        else:
            self._send(500, json.dumps({'ok': False}),
                       content_type='application/json; charset="utf-8"')

    @staticmethod
    def _fmt_speed(bps):
        try:
            bps = float(bps)
        except Exception:
            return ''
        if bps >= 1024 * 1024:
            return '%.1f MB/s' % (bps / 1024.0 / 1024.0)
        if bps >= 1024:
            return '%.0f KB/s' % (bps / 1024.0)
        return '%.0f B/s' % bps

    @staticmethod
    def _unique_path(folder, name):
        base, ext = os.path.splitext(name)
        cand = os.path.join(folder, name)
        i = 1
        while os.path.exists(cand):
            cand = os.path.join(folder, '%s (%d)%s' % (base, i, ext))
            i += 1
        return cand

    def do_SUBSCRIBE(self):
        service = self._service_from_path(self.path)
        cb = self.headers.get('CALLBACK', '') or ''
        timeout_hdr = self.headers.get('TIMEOUT', '') or 'Second-1800'
        sid_hdr = self.headers.get('SID', '') or ''
        notifier = getattr(self.server, 'notifier', None)
        if sid_hdr and notifier is not None:
            if sid_hdr in notifier._subs:
                notifier.refresh(sid_hdr, timeout_hdr)
                self._send(200, '', extra={'SID': sid_hdr, 'TIMEOUT': timeout_hdr,
                                           'SERVER': ssdp.SERVER_STR})
                self.server.log('[DLNA] 事件订阅续订 SID=%s...' % sid_hdr[:20])
                return
            self._send(412, '', extra={'SID': '', 'TIMEOUT': timeout_hdr})
            return
        m = re.search(r'<(http://[^>]+)>', cb)
        if not m or not service:
            self._send(412, '', extra={'SID': '', 'TIMEOUT': timeout_hdr})
            return
        callback = m.group(1)
        sid = self.server.notifier.subscribe(service, callback, timeout_hdr)
        self._send(200, '', extra={
            'SID': sid, 'TIMEOUT': timeout_hdr, 'SERVER': ssdp.SERVER_STR})
        self.server.log('[DLNA] 事件订阅 %s <- %s (SID=%s)'
                        % (service.split(':')[-2] if ':' in service else service,
                           callback, sid[:20] + '...'))
        self.server.notifier.push_initial(service)

    def do_UNSUBSCRIBE(self):
        sid = self.headers.get('SID', '') or ''
        if sid:
            self.server.notifier.unsubscribe(sid)
        self._send(200, '')

    @staticmethod
    def _service_from_path(path):
        if 'AVTransport' in path:
            return 'AVTransport'
        if 'RenderingControl' in path:
            return 'RenderingControl'
        if 'ConnectionManager' in path:
            return 'ConnectionManager'
        return None

    def do_NOTIFY(self):
        length = int(self.headers.get('Content-Length', 0) or 0)
        if length:
            try:
                self.rfile.read(length)
            except Exception:
                pass
        self._send(200, '')


class _NotifyRequest(urllib.request.Request):

    def get_method(self):
        return 'NOTIFY'


class EventNotifier:

    def __init__(self, state, log=print):
        self.state = state
        self.log = log
        self._subs = {}
        self._seq = {}
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}))

    def subscribe(self, service, callback, timeout):
        sid = 'uuid:%s' % _uuid.uuid4()
        self._subs[sid] = (service, callback, timeout)
        self._seq[sid] = 0
        return sid

    def unsubscribe(self, sid):
        self._subs.pop(sid, None)
        self._seq.pop(sid, None)

    def refresh(self, sid, timeout):
        if sid in self._subs:
            svc, cb, _old = self._subs[sid]
            self._subs[sid] = (svc, cb, timeout)

    def _lastchange_body(self, service, props):
        ns = 'urn:schemas-upnp-org:metadata-1-0/%s/' % service
        inner = ''.join('<%s val="%s"/>' % (k, escape(str(v)))
                        for k, v in props.items())
        last = ('<Event xmlns="%s"><InstanceID val="0">%s</InstanceID></Event>'
                % (ns, inner))
        return ('<?xml version="1.0" encoding="utf-8"?>'
                '<e:propertyset xmlns:e="urn:schemas-upnp-org:event-1-0">'
                '<e:property><LastChange>%s</LastChange></e:property>'
                '</e:propertyset>' % escape(last))

    def push_initial(self, service):
        if service == 'AVTransport':
            props = {'TransportState': self.state.transport_state,
                     'TransportStatus': 'OK',
                     'CurrentTrackURI': self.state.current_uri,
                     'NumberOfTracks': '1'}
        elif service == 'RenderingControl':
            props = {'Volume': str(self.state.volume),
                     'Mute': str(self.state.mute)}
        else:
            return
        self._post(service, props, initial=True)

    def notify_state(self, state=None):
        st = state or self.state
        self._post('AVTransport',
                   {'TransportState': st.transport_state,
                    'TransportStatus': 'OK',
                    'CurrentTrackURI': st.current_uri})

    def notify_volume(self, state=None):
        st = state or self.state
        self._post('RenderingControl',
                   {'Volume': str(st.volume), 'Mute': str(st.mute)})

    def _post(self, service, props, initial=False):
        if not self._subs:
            return
        body = self._lastchange_body(service, props)
        threading.Thread(target=self._post_async,
                         args=(service, body, initial), daemon=True).start()

    def _post_async(self, service, body, initial):
        for sid, (svc, callback, _to) in list(self._subs.items()):
            if svc != service:
                continue
            seq = self._seq.get(sid, 0)
            if not initial:
                self._seq[sid] = seq + 1
            req = _NotifyRequest(
                callback, data=body.encode('utf-8'),
                headers={'Content-Type': 'text/xml; charset="utf-8"',
                         'NT': 'upnp:event', 'NTS': 'upnp:propchange',
                         'SID': sid, 'SEQ': str(seq)})
            try:
                self._opener.open(req, timeout=3).read()
                self.log('[事件] 已推送 %s -> %s (SEQ=%d)'
                         % (service, callback, seq))
            except Exception as e:
                self.log('[事件] 推送失败 %s: %s' % (callback, e))


class DlnaServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class DlnaStack:

    def __init__(self, ip, port, name, state, log=print):
        self.ip = ip
        self.port = port
        self.name = name
        self.state = state
        self.log = log
        self.http = DlnaServer(('0.0.0.0', port), _Handler)
        self.http.app_ip = ip
        self.http.app_port = port
        self.http.app_name = name
        self.http.state = state
        self.http.log = log
        self.tv_mode = False
        self.http.tv_mode = False
        self.ssdp = ssdp.SSDPServer(ip, port, name, log=log)
        self.notifier = EventNotifier(state, log=log)
        self.http.notifier = self.notifier
        state.on_transport_change = self._on_transport_change
        state.on_volume_change = self._on_volume_change
        self._thread = None

    def _on_transport_change(self, state):
        try:
            self.notifier.notify_state(state)
        except Exception:
            pass

    def _on_volume_change(self, state):
        try:
            self.notifier.notify_volume(state)
        except Exception:
            pass

    def set_tv_mode(self, on):
        self.tv_mode = bool(on)
        self.http.tv_mode = bool(on)
        try:
            self.state.tv_mode = bool(on)
        except Exception:
            pass
        try:
            self.ssdp.announce()
        except Exception:
            pass
        return self.tv_mode

    def start(self):
        self._thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self._thread.start()
        self.ssdp.start()
        self.log('[DLNA] 控制服务已启动: http://%s:%d/device.xml' % (self.ip, self.port))

    def stop(self):
        try:
            if self._thread is not None:
                self.http.shutdown()
        except Exception:
            pass
        try:
            self.http.server_close()
        except Exception:
            pass
        self._thread = None
        self.ssdp.shutdown()
