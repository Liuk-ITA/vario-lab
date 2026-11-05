# Generated RAM bundle; edit src/*.py instead.

# ---- bmp581.py ----
"""BMP581-only adapter. Based on the physically validated WM4 acquisition script."""
class BMP581:
    name = 'BMP581'
    hz = 80
    watermark = 4
    period_ms = 12.5
    def __init__(self, bus, sleep_ms, address=None):
        self.bus = bus
        devices = bus.scan() if address is None else [address]
        self.address = next((a for a in (0x46, 0x47) if a in devices), None)
        if self.address is None: raise RuntimeError('BMP581 assente: %s' % devices)
        if self.read(0x01) != 0x50: raise RuntimeError('BMP581 chip ID non valido')
        self.seq = 0
        self.first_ms = None
        self.max_fifo = self.near_full = self.invalid = self.errors = 0
        self.readback = {}
        self.write(0x37, 0x30)  # standby, 80 Hz
        sleep_ms(12)
        for reg, value in ((0x15,0),(0x18,0),(0x36,0x62),(0x30,3),(0x31,0),
                           (0x16,4),(0x18,3),(0x15,6),(0x37,0x31)):
            self.write(reg,value)
        sleep_ms(65)
        expected = {0x36:0x62,0x37:0x31,0x38:0xA2,0x30:3,0x31:0,0x18:3,0x16:4,0x15:6}
        for reg, value in expected.items():
            actual = self.read(reg)
            self.readback[reg] = actual
            mask = 0xBF if reg == 0x38 else 0x7F if reg == 0x37 else 0xFF
            if actual & mask != value: raise RuntimeError('CFG reg %02X: %02X != %02X' % (reg,actual,value))
    def read(self,reg): return self.bus.readfrom_mem(self.address,reg,1)[0]
    def write(self,reg,value): self.bus.writeto_mem(self.address,reg,bytes((value,)))
    def poll(self, now_ms, force=False):
        n = self.read(0x17) & 0x1F
        self.max_fifo = max(n,self.max_fifo)
        if n < (1 if force else self.watermark): return None
        if n > 16: raise RuntimeError('FIFO count PT fuori range: %d' % n)
        if n >= 15: self.near_full += 1
        data = self.bus.readfrom_mem(self.address,0x29,n*6)
        if len(data) != n*6: raise RuntimeError('Lettura FIFO incompleta')
        if self.first_ms is None: self.first_ms = now_ms - (n-1)*self.period_ms
        first_seq = self.seq + 1
        samples = []
        for i in range(n):
            off = i*6
            tr = data[off] | data[off+1]<<8 | data[off+2]<<16
            if tr & 0x800000: tr -= 0x1000000
            pr = data[off+3] | data[off+4]<<8 | data[off+5]<<16
            if pr & 0x800000: pr -= 0x1000000
            p,tc = pr/64.0,tr/65536.0
            self.seq += 1
            nominal = self.first_ms+(self.seq-1)*self.period_ms
            batch = now_ms-(n-1-i)*self.period_ms
            if not (30000<p<125000 and -50<tc<100): self.invalid += 1; continue
            samples.append((self.seq,nominal,batch,p,tc))
        return first_seq,n,now_ms,samples


# ---- sensor_bus.py ----
"""Probe Grove first, then the 3.3V header; accept BMP581 chip ID only."""

def discover_bmp581(I2C,Pin,power,sleep_ms,report=print):
    power.setExtOutput(True);sleep_ms(30)
    for name,sda,scl in (('GROVE',9,10),('HEADER',1,0)):
        bus=None
        try:
            bus=I2C(0,scl=Pin(scl),sda=Pin(sda),freq=400000)
            addresses=bus.scan()
            report('I,SCAN,%s,sda=%d,scl=%d,addresses=%s'%(name,sda,scl,','.join('%02X'%a for a in addresses)))
            address=None
            for a in (0x46,0x47):
                if a in addresses:
                    try:valid=bus.readfrom_mem(a,0x01,1)[0]==0x50
                    except OSError:valid=False
                    if valid:address=a;break
        except OSError as e:
            report('I,SCAN,%s,unavailable=%s'%(name,e));address=None
        if address is not None:
            external=name=='GROVE'
            if not external:
                power.setExtOutput(False);sleep_ms(5)
                try:alive=bus.readfrom_mem(address,0x01,1)[0]==0x50
                except OSError:alive=False
                if not alive:raise RuntimeError('BMP581 header senza alimentazione: collegare VIN a 3V3_L2')
            sensor=BMP581(bus,sleep_ms,address=address)
            info={'bus':name,'sda':sda,'scl':scl,'ext5v':external,'address':address}
            report('I,SENSOR,%s,sda=%d,scl=%d,ext5v=%d,address=%02X'%(name,sda,scl,external,address))
            return sensor,info
        if bus is not None:
            try:bus.deinit()
            except (AttributeError,OSError):pass
    raise RuntimeError('BMP581 assente: Grove SDA9/SCL10 e header SDA1/SCL0')


# ---- external_buttons.py ----
"""Powered U025 keys: no pin access while the barometer occupies Grove."""
class ExternalKeys:
    def __init__(self):
        self.raw=[False,False];self.stable=[False,False];self.changed=[0,0]
        self.start=[None,None];self.held=[False,False];self.armed=[False,False]
        self.chord=False
    def update(self,now,audio,page):
        actions=[]
        for i,value in enumerate((bool(audio),bool(page))):
            if value!=self.raw[i]:self.raw[i]=value;self.changed[i]=now
            if now-self.changed[i]>=30 and value!=self.stable[i]:
                self.stable[i]=value
                if value:
                    self.start[i]=now;self.held[i]=False
                else:
                    if self.armed[i] and self.start[i] is not None and not self.held[i] and not self.chord:
                        actions.append('frequency' if i==0 else 'page')
                    self.start[i]=None;self.armed[i]=True
            if not value and now-self.changed[i]>=30:self.armed[i]=True
        if all(self.stable):self.chord=True;actions=[]
        if self.stable[0] and self.armed[0] and not self.held[0] and not self.chord and now-self.start[0]>=700:
            self.held[0]=True;actions.append('pattern')
        if not any(self.stable):self.chord=False
        return actions

class GroveButtons:
    def __init__(self,Pin,sensor_info,enabled=False,power=None):
        self.keys=ExternalKeys();self.pins=None
        if sensor_info['bus']=='HEADER':
            if power is not None:power.setExtOutput(bool(enabled))
            sensor_info['ext5v']=bool(enabled)
            if enabled:
                self.pins=(Pin(9,mode=Pin.IN,pull=None),Pin(10,mode=Pin.IN,pull=None))
    def update(self,now):
        if self.pins is None:return ()
        return self.keys.update(now,not self.pins[0].value(),not self.pins[1].value())


# ---- remote_hid.py ----
"""Optional HID keyboard alongside NUS; F1 is bound to an action in XCTrack.

Original small report descriptor: one eight-byte boot-compatible keyboard report.
Bond storage is deferred out of the BLE IRQ and acquisition is paused by the app.
"""
import json,binascii
HID_MAP=bytes((0x05,1,0x09,6,0xA1,1,0x05,7,0x19,0xE0,0x29,0xE7,
               0x15,0,0x25,1,0x75,1,0x95,8,0x81,2,
               0x75,8,0x95,1,0x81,1,
               0x05,7,0x19,0,0x29,0x65,0x15,0,0x25,0x65,
               0x75,8,0x95,6,0x81,0,0xC0))

class RemoteHID:
    def __init__(self,path='/flash/stick_vario_ble_bonds_v1.json'):
        self.path=path;self.secrets=[];self.revision=0;self.saved_revision=0
        self.pairing=None;self.pair_started=None;self.pair_armed=False;self.events=[];self.security=None;self.secret_gets=0;self.secret_sets=0
        self.queue=[];self.release_at=None;self.key_conn=None;self.encrypted=set();self.errors=0
        try:
            with open(path) as f:rows=json.load(f)
            if not isinstance(rows,list) or len(rows)>32:raise ValueError('bond count')
            for t,k,v in rows:
                if type(t)!=int or not isinstance(k,str) or not isinstance(v,str) or len(k)>128 or len(v)>256:raise ValueError('bond format')
                self.secrets.append((t,binascii.unhexlify(k),binascii.unhexlify(v)))
        except OSError:pass
        except Exception:self.secrets=[];self.errors+=1
    @property
    def dirty(self):return self.revision!=self.saved_revision
    @dirty.setter
    def dirty(self,value):
        if value:self.revision+=1
        else:self.saved_revision=self.revision
    def service(self,U):
        return (U(0x1812),((U(0x2A4A),2),(U(0x2A4B),2),
                (U(0x2A4D),0x0212,((U(0x2908),2),)),
                (U(0x2A4C),4)))
    def configure(self,ble):
        # Apply before startup and again before advertising; preserve the early secret IRQ.
        self.ble=ble
        ble.config(io=1)
        ble.config(mitm=True)
        ble.config(le_secure=True)
        ble.config(bond=True)
    def bind(self,ble,handles):
        self.ble=ble
        info,report_map,self.report,ref,self.control=handles
        for handle,data in ((info,b'\x11\x01\x00\x02'),(report_map,HID_MAP),
                            (self.report,bytes(8)),(ref,b'\x00\x01')):
            ble.gatts_write(handle,data)
    def irq(self,event,data):
        if event==28:
            conn,encrypted,authenticated,bonded,key_size=data
            self.security=(conn,bool(encrypted),bool(authenticated),bool(bonded),key_size)
            self.events.append(('security',)+self.security)
            if len(self.events)>8:self.events.pop(0)
            self.pairing=None
            if encrypted:self.encrypted.add(conn)
            else:self.encrypted.discard(conn)
        elif event==31:
            conn,action,passkey=data
            self.pairing=(conn,action,passkey);self.pair_started=None;self.pair_armed=False
            if action==3:
                import os
                code=int.from_bytes(os.urandom(4),'little')%1000000
                self.pairing=(conn,action,code)
                self.ble.gap_passkey(conn,action,code)
            elif action!=4:
                # Input-only is incompatible with DISPLAY_YESNO; do not invent a PIN.
                self.ble.gap_disconnect(conn);self.pairing=None;self.errors+=1
            self.events.append(('pair_request',conn,action))
            if len(self.events)>8:self.events.pop(0)
        elif event==29:
            self.secret_gets+=1
            sec_type,index,key=data
            if key is None:
                matches=[v for t,k,v in self.secrets if t==sec_type]
                return matches[index] if 0<=index<len(matches) else None
            return next((v for t,k,v in self.secrets if t==sec_type and k==bytes(key)),None)
        elif event==30:
            self.secret_sets+=1
            sec_type,key,value=data;key=bytes(key)
            rows=[r for r in self.secrets if not(r[0]==sec_type and r[1]==key)]
            if value is not None:
                if len(rows)>=32:return False
                rows.append((sec_type,key,bytes(value)))
            self.secrets=rows;self.revision+=1
            self.events.append(('secret_set',sec_type,len(rows)))
            if len(self.events)>8:self.events.pop(0)
            return True
    def pairing_buttons(self,now,a,b):
        if self.pairing is None:return False
        if self.pair_started is None:self.pair_started=now
        conn,action,code=self.pairing
        if not a and not b:self.pair_armed=True
        if now-self.pair_started>=30000:
            if action==4:self.ble.gap_passkey(conn,action,0)
            else:self.ble.gap_disconnect(conn)
            self.pairing=None
        elif self.pair_armed and (a or b):
            if action==4:self.ble.gap_passkey(conn,action,0 if b else 1);self.pairing=None
            elif b:self.ble.gap_disconnect(conn);self.pairing=None
        return True
    def save(self):
        import os
        revision=self.revision
        rows=[(t,binascii.hexlify(k).decode(),binascii.hexlify(v).decode()) for t,k,v in self.secrets]
        with open(self.path+'.tmp','w') as f:json.dump(rows,f)
        getattr(os,'replace',os.rename)(self.path+'.tmp',self.path)
        # New keys may arrive from the BLE IRQ while the file is being written.
        self.saved_revision=revision
    def disconnect(self,conn):
        self.encrypted.discard(conn)
        if self.pairing and self.pairing[0]==conn:self.pairing=None
        if self.key_conn==conn:self.key_conn=None;self.release_at=None
        # Never replay old clicks on a later connection.
        self.queue=[]
    def click(self):
        if not self.encrypted or len(self.queue)>=4:return False
        self.queue.append(0x3A) # USB HID F1, not ASCII.
        return True
    def pump(self,now):
        if self.release_at is not None:
            if now<self.release_at:return
            try:self.ble.gatts_notify(self.key_conn,self.report,bytes(8))
            except OSError:
                self.errors+=1;return # Retry release before allowing another key-down.
            self.release_at=None;self.key_conn=None
        if self.queue and self.encrypted:
            conn=min(self.encrypted);key=self.queue.pop(0)
            try:self.ble.gatts_notify(conn,self.report,bytes((0,0,key,0,0,0,0,0)))
            except OSError:self.errors+=1;return
            self.key_conn=conn;self.release_at=now+80
    def close(self):
        if self.key_conn is not None:
            try:self.ble.gatts_notify(self.key_conn,self.report,bytes(8))
            except OSError:pass


# ---- filters.py ----
"""Dependency-free causal estimators matching Vario Lab; no hardware imports."""
import math

def alpha(dt,tau): return 1.0-math.exp(-dt/tau)
def relative_height(p,p0):
    return 288.15/.0065*(1.0-(p/p0)**(287.05287*.0065/9.80665))

class AllFilters:
    def __init__(self):
        self.last = None
        self.rows = []
        self.sky_rows = []
    def update(self,t,z,p,p0):
        if self.last is None:
            self.last = self.start = t
            self.z = self.x = self.fast = self.slow = z
            self.v = self.kv = self.dual = 0.0
            self.P = (.0004,0.,0.,1.)
            self.rows = [(t,z)]
            self.mt,self.mz,self.stt,self.stz=t,z,0.,0.
            self.spx,self.sP = p,.04
            self.sky_rows = [(t,relative_height(p,p0))]
            return {'lp':0.,'reg':None,'kal':0.,'dual':0.,'sky':None}
        dt = t-self.last
        if dt<=0: raise ValueError('Tempo campione non crescente')
        self.last = t
        old = self.z
        self.z += alpha(dt,.25)*(z-self.z)
        self.v += alpha(dt,.20)*((self.z-old)/dt-self.v)
        # Incremental centered moments: same trailing OLS, O(1) work per sample.
        count=len(self.rows)+1
        delta_t,delta_z=t-self.mt,z-self.mz
        self.mt+=delta_t/count
        self.mz+=delta_z/count
        self.stt+=delta_t*(t-self.mt)
        self.stz+=delta_t*(z-self.mz)
        self.rows.append((t,z))
        while self.rows and self.rows[0][0]<t-.60-1e-9:
            tt,zz=self.rows.pop(0)
            n=len(self.rows)
            new_mt=self.mt-(tt-self.mt)/n
            new_mz=self.mz-(zz-self.mz)/n
            self.stt-=(tt-self.mt)*(tt-new_mt)
            self.stz-=(tt-self.mt)*(zz-new_mz)
            self.mt,self.mz=new_mt,new_mz
        reg=None
        if t-self.start>=.60-1e-9 and len(self.rows)>=3 and self.stt>0:
            reg=self.stz/self.stt
        a,b,c,d = self.P
        q,R = .020,.0004
        p00 = a+dt*(b+c)+dt*dt*d+q*dt**3/3
        p01,p10,p11 = b+dt*d+q*dt*dt/2,c+dt*d+q*dt*dt/2,d+q*dt
        k0,k1 = p00/(p00+R),p10/(p00+R)
        prediction = self.x+dt*self.kv
        residual = z-prediction
        self.x = prediction+k0*residual
        self.kv += k1*residual
        self.P = ((1-k0)**2*p00+k0*k0*R,
                  (1-k0)*(p01-k1*p00)+k0*k1*R,
                  (1-k0)*(p10-k1*p00)+k1*k0*R,
                  p11-k1*(p01+p10)+k1*k1*p00+k1*k1*R)
        self.fast += alpha(dt,.19)*(z-self.fast)
        self.slow += alpha(dt,.39)*(z-self.slow)
        lag = dt/(math.exp(dt/.39)-1)-dt/(math.exp(dt/.19)-1)
        self.dual += alpha(dt,.19)*((self.fast-self.slow)/lag-self.dual)
        self.sP += .01*dt
        sk = self.sP/(self.sP+.04)
        self.spx += sk*(p-self.spx)
        self.sP *= 1-sk
        sz = relative_height(self.spx,p0)
        self.sky_rows.append((t,sz))
        target = t-.5
        while len(self.sky_rows)>2 and self.sky_rows[1][0]<=target: self.sky_rows.pop(0)
        sky = None
        if target>=self.start-1e-9 and len(self.sky_rows)>=2:
            aa,bb = self.sky_rows[:2]
            f = max(0.,min(1.,(target-aa[0])/(bb[0]-aa[0])))
            sky = (sz-aa[1]-f*(bb[1]-aa[1]))/.5
        return {'lp':self.v,'reg':reg,'kal':self.kv,'dual':self.dual,'sky':sky}

class FilterBank:
    def __init__(self): self.zero()
    def zero(self):
        self.reference = None
        self.cal_start = None
        self.cal_sum = self.cal_count = 0
        self.restart()
    def restart(self):
        self.filters = AllFilters()
        self.filter_start = self.last = None
        self.values = {k:None for k in ('lp','reg','kal','dual','sky')}
        self.slow = self.values.copy()
        self.ready = False
        self.height = 0.
    def update(self,t,p,tc):
        if self.reference is None:
            if self.cal_start is None: self.cal_start = t
            self.cal_sum += p
            self.cal_count += 1
            if t-self.cal_start<2.: return
            self.reference = self.cal_sum/self.cal_count
        self.height = relative_height(p,self.reference)
        if self.filter_start is None: self.filter_start = t
        self.values = self.filters.update(t,self.height,p,self.reference)
        dt = t-self.last if self.last is not None else 0.
        self.last = t
        for key,v in self.values.items():
            if v is None: self.slow[key] = None
            elif self.slow[key] is None: self.slow[key] = v
            else: self.slow[key] += alpha(dt,1.5)*(v-self.slow[key])
        self.ready = t-self.filter_start>=3.


# ---- sound.py ----
"""Non-blocking tone scheduler. Curve math follows Vario Lab; hardware renderer differs."""
import math

PROFILES = (
    ('KALMAN','kal','classic'),('REGRESS','reg','classic'),('PASSABASSO','lp','classic'),
    ('RC EMA','dual','classic'),('SKYBEAN','sky','curves'),
    ('DUE MEDIE','kal','dualmean'),('CURVE','kal','curves'),('DOPPIO','kal','pair'))
CURVES = ((-5,150,.30,.20),(-1,250,.30,.20),(0,500,.24,.40),(.2,560,.22,.34),
          (.5,660,.18,.27),(1,800,.15,.20),(2,1030,.12,.13),(4,1350,.08,.08),(6,1600,.06,.05))

def curve(v):
    i = 0
    while i<len(CURVES)-2 and v>CURVES[i+1][0]: i+=1
    a,b = CURVES[i:i+2]
    f = max(0.,min(1.,(v-a[0])/(b[0]-a[0])))
    return tuple(a[k]+f*(b[k]-a[k]) for k in (1,2,3))

def sound_state(v,slow,kind,was_climbing=False):
    if v is None: return ('silent',0.,1.,0.,0.,0.,0.,0.)
    threshold = .06 if was_climbing else .10
    if v>=threshold:
        hz = max(150,min(1800,550+180*v))
        period = max(.12,.65/(1+max(v,0)*1.4))
        if kind=='dualmean':
            return ('climb',hz,period,.5,max(150,min(1800,550+180*(slow if slow is not None else v))),.5,0.,0.)
        if kind in ('curves','pair'):
            hz,length,pause = curve(v)
            if kind=='pair':
                second = curve(v+.5)[0]
                period = 2*length+.04+pause
                return ('climb',hz,period,(2*length+.04)/period,second,0.,length,.04)
            return ('climb',hz,length+pause,length/(length+pause),0.,0.,0.,0.)
        return ('climb',hz,period,.45,0.,0.,0.,0.)
    if v<=-.5:
        if kind=='pair':
            hz,length,pause = curve(v)
            period = 2*length+.04+pause
            return ('sink',hz,period,(2*length+.04)/period,curve(v-.5)[0],0.,length,.04)
        hz = curve(v)[0] if kind=='curves' else max(120,min(400,300+45*v))
        return ('sink',hz,1.,1.,0.,0.,0.,0.)
    return ('silent',0.,1.,0.,0.,0.,0.,0.)

BASE_NOTES=(550,1000,1250,1500,1750,2000,2250,2500)
VOLUME_LEVELS=(0,64,110,160,190,220,255)

class TuningControls:
    """Press duration state machine; a hold never becomes a profile click."""
    def __init__(self):self.a_start=self.b_start=None;self.a_held=self.b_held=False;self.next_repeat=0
    def update(self,now,a,b):
        actions=[]
        if a:
            if self.a_start is None:self.a_start=now;self.a_held=False;self.next_repeat=now+600
            if now>=self.next_repeat:
                self.a_held=True;actions.append('note');self.next_repeat=now+800
        elif self.a_start is not None:
            if not self.a_held and now-self.a_start>=30:actions.append('profile')
            self.a_start=None
        if b:
            if self.b_start is None:self.b_start=now;self.b_held=False
            if not self.b_held and now-self.b_start>=900:self.b_held=True;actions.append('zero')
        elif self.b_start is not None:
            if not self.b_held and now-self.b_start>=30:actions.append('volume')
            self.b_start=None
        return actions

class PWMPiezo:
    """Speaker-compatible GPIO driver; no direct connection to the codec output."""
    def __init__(self,pin=5):
        import machine,time
        self.clock=time
        self.pin=machine.Pin(pin,machine.Pin.OUT,value=0)
        self.pwm=machine.PWM(self.pin,freq=1500,duty_u16=0)
        self.timer=machine.Timer(0)
        self.volume=160
        self.deadline=None
    def begin(self):pass
    def setVolume(self,value):self.volume=max(0,min(255,int(value)))
    def setChannelVolume(self,channel,value):pass
    def _expire(self,timer):
        # A callback queued before a newer tone must not silence that newer tone.
        if self.deadline is not None and self.clock.ticks_diff(self.clock.ticks_ms(),self.deadline)>=0:
            self.pwm.duty_u16(0)
            self.deadline=None
    def tone(self,hz,duration,channel=0,replace=True):
        self.timer.deinit()
        self.pwm.freq(max(150,min(4500,int(hz))))
        # Duty is an approximate loudness control, also changing harmonic content.
        self.pwm.duty_u16(self.volume*32768//255)
        self.deadline=self.clock.ticks_add(self.clock.ticks_ms(),max(1,int(duration)))
        self.timer.init(period=max(1,int(duration)),mode=self.timer.ONE_SHOT,callback=self._expire)
    def stop(self,channel=0):
        self.timer.deinit()
        self.deadline=None
        self.pwm.duty_u16(0)
    def close(self):
        self.stop()
        self.pwm.deinit()
        self.pin.value(0)

class ToneAudio:
    def __init__(self,speaker):
        self.speaker = speaker
        self.phase = 0.
        self.last = None
        self.mode = 'silent'
        self.base_hz=1500
        self.requested_volume=160
        self.master_volume=160
        self.preview_until=0
        self.frequency = float(self.base_hz)
        self.on = False
        self.last_send = -1000
        self.calls = 0
        self.errors = 0
        speaker.begin()
        speaker.setVolume(self.master_volume)
        speaker.setChannelVolume(0,255)
    def stop(self):
        self.preview_until=0
        self.speaker.stop(0)
        self.on = False
        self.mode = 'silent'
        self.last = None
    def set_volume(self,value,usb=False):
        value=max(0,min(255,int(value)))
        effective=min(value,255 if usb else 190)
        self.requested_volume=value
        if effective!=self.master_volume:
            self.master_volume=effective;self.speaker.setVolume(effective)
        if not effective:self.stop()
    def preview(self,now):
        self.stop()
        if self.master_volume:
            self.frequency=float(self.base_hz)
            self.speaker.tone(self.base_hz,160,0,True)
            self.calls+=1;self.preview_until=now+160
    def transpose(self,a,kind):
        if a[0]=='silent':return a
        mode,hz,period,duty,second,split,length,gap=a
        offset=self.base_hz-(curve(0)[0] if kind in ('curves','pair') else 550)
        hz=max(150,min(4500,hz+offset))
        second=max(150,min(4500,second+offset)) if second else 0.
        return mode,hz,period,duty,second,split,length,gap
    def update(self,now,v,slow,kind,enabled):
        if now<self.preview_until:
            self.last=now
            return
        if not enabled:
            if self.on: self.stop()
            self.last = now
            return
        a = self.transpose(sound_state(v,slow,kind,self.mode=='climb'),kind)
        mode,hz,period,duty,second,split,length,gap = a
        dt = (now-self.last)/1000. if self.last is not None else 0.
        self.last = now
        if mode!=self.mode:
            self.phase = 0.
            dt = 0.
        self.mode = mode
        if mode=='silent':
            if self.on: self.speaker.stop(0);self.on=False
            return
        self.phase = (self.phase+dt/period)%1.
        on = self.phase<duty
        end_phase = duty
        if second:
            if split:
                if self.phase>=duty*split: hz=second
            else:
                pos = self.phase*period
                on = pos<length or length+gap<=pos<2*length+gap
                if pos>=length+gap:
                    hz=second
                    end_phase=(2*length+gap)/period
                else:end_phase=length/period
        tau = .002 if kind=='dualmean' else .025
        self.frequency += (1.-math.exp(-dt/tau))*(hz-self.frequency)
        if not on:
            if self.on: self.speaker.stop(0);self.on=False
            return
        # Hardware owns the end of this ON segment, even while LCD/I2C blocks.
        # Continuous sink must survive long loop intervals as well.
        duration = 1000 if duty>=1 and not (second and not split) else max(1,int((end_phase-self.phase)*period*1000))
        # Keep pitch updates bounded; never replace an entire beep with a 60ms lease.
        if not self.on or now-self.last_send>=20:
            try:
                self.speaker.tone(int(self.frequency),duration,0,True)
                self.last_send=now;self.on=True;self.calls+=1
            except Exception:
                self.errors+=1
                self.speaker.stop(0);self.on=False


# ---- audio_tables.py ----
import binascii
AUDIO_TABLES={k:binascii.a2b_base64(v) for k,v in {('dolce', 1800): 'AABvBNwIRQ2oEQIWURqUHsgi6yb8Kvgu3jKsNmE6+j14QddEGEg4SzdOFVHPU2ZW2VgnW1BdVF8zYexigWTwZTpnYWhjaUNq/2qaaxVsb2yqbMhsyGytbHhsKWzDa0Zrs2oNalRpimiwZ8dm0mXQZMNjrWKPYWlgPV8MXtdcn1tkWihZ61euVnFVNVT7UsJRi1BXTyVO9kzKS6BKeUlUSDFHEEbxRNNDt0KaQX5AYj9FPic9BjzkOr85ljhpNzg2AzXHM4cyQDHyL50uQi3eK3MqACmFJwImdiTiIkYhoh/1HUEchRrCGPgWJxVQE3MRkA+pDb4LzgncB+cF8AP4AQAACP4Q/Bn6JPgy9kL0V/Jw8I3usOzZ6gjpPud75b/jC+Je4LreHt2K2/7Ze9gA143VItS+0mPRDtDAznnNOcz9ysjJl8hqx0HGHMX6w9nCu8GewIK/Zr5JvS28D7vwuc+4rLeHtmC1NrQKs9uxqbB1rz6uBa3Lq4+qUqkVqNimnKVhpCmj9KHDoJefcZ5TnT2cMJsumjmZUJh2l6yW85VNlbqUPZTXk4iTU5M4kziTVpORk+uTZpQBlb2VnZafl8aYEJp/mxSdzZ6soLCi2aQnp5qpMazrrsmxyLTotym7iL4Gwp/FVMkizQjRBNUV2TjdbOGv5f7pWO678iT3kfs=', ('ricco', 1800): 'AAA+BncMpBK/GMMeqiRvKg0wfjW/Oso/nUQySYhNmlFnVe1YKlwdX8RhIWQyZvhndWmpapdrP2ylbMtstWxlbN9rJms/aixp9GeYZh9limPgYSRgWl6GXKtazVjwVhdVRFN7Ub1PDk5uTOBKZUn+R6xGbkVGRDRDNkJNQXdAtT8DP2I+0D1LPdE8YDz3O5Q7NTvYOno6Gzq4OU854DhoOOc3WjfCNhw2aTWnNNcz9zIJMgwxADDmLr8tiixJK/0ppyhIJ+EldCQBI4ohECCVHhkdnxsmGrEYQBfUFW4UDhO2EWUQHA/cDaMMcwtLCisJEgj/BvMF7ATqA+wC8QH4AAAACP8P/hT9FvwU+w36Afnu99X2tfWN9F3zJPLk8JvvSu7y7JLrLOrA6E/n2uVh5Ofia+Hw33be/9yM2x/auNhZ1wPWt9R200HSGtEA0PTO980JzSnMWcuXyuTJPsmmyBnImMcgx7HGSMblxYbFKMXLxGzECcSgwy/DtcIwwp7B/cBLwIm/s77Kvcy8uruSulS5AribtiC1krPysUOwha68rOmqEKkzp1WleqOmodyfIJ52nOGaaJkMmNSWwZXalCGUm5NLkzWTW5PBk2mUV5WLlgiYzpnfmzye46DWoxOnmapmrniyzrZjuzbAQcWCyvPPkdVW2z3hQedc7Ynzwvk=', ('dispari', 1800): 'AACTCBcRfBm0IbApYjG/OLo/SUZiTP5RF1enW6xfJGMOZm1oQ2qWa2psx2y1bD9sbWtLauRoRWd5ZY1jjGGCX3pdgFudWdlXPlbSVJpTnFLbUVlRFlETUU5Rw1FwUk9TW1SNVd9WSFjBWUJbw1w7XqRf9mApYjhjHmTWZFtlrWXIZa1lW2XWZB5kOGMpYvZgpF87XsNcQlvBWUhY31aNVVtUT1NwUsNRTlETURZRWVHbUZxSmlPSVD5W2VedWYBbel2CX4xhjWN5ZUVn5GhLam1rP2y1bMdsamyWa0NqbWgOZiRjrF+nWxdX/lFiTElGuj+/OGIxsCm0IXwZFxGTCAAAbffp7oTmTN5Q1p7OQcdGwLe5nrMCrumoWaRUoNyc8pmTl72VapSWkzmTS5PBk5OUtZUcl7uYh5pznHSefqCGooCkY6YnqMKpLqtmrGStJa6nruqu7a6yrj2ukK2xrKWrc6ohqbinP6a+pD2jxaFcoAqf153InOKbKpulmlOaOJpTmqWaKpvim8ic150Kn1ygxaE9o76kP6a4pyGpc6qlq7GskK09rrKu7a7qrqeuJa5krWasLqvCqSeoY6aApIaifqB0nnOch5q7mByXtZWTlMGTS5M5k5aTapS9lZOX8pncnFSgWaTpqAKunrO3uUbAQceezlDWTN6E5unubfc=', ('fm_ferma', 1800): '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', ('dolce', 3000): 'AABvBNwIRQ2oEQIWURqUHsgi6yb8Kvgu3jKsNmE6+j14QddEGEg4SzdOFVHPU2ZW2VgnW1BdVF8zYexigWTwZTpnYWhjaUNq/2qaaxVsb2yqbMhsyGytbHhsKWzDa0Zrs2oNalRpimiwZ8dm0mXQZMNjrWKPYWlgPV8MXtdcn1tkWihZ61euVnFVNVT7UsJRi1BXTyVO9kzKS6BKeUlUSDFHEEbxRNNDt0KaQX5AYj9FPic9BjzkOr85ljhpNzg2AzXHM4cyQDHyL50uQi3eK3MqACmFJwImdiTiIkYhoh/1HUEchRrCGPgWJxVQE3MRkA+pDb4LzgncB+cF8AP4AQAACP4Q/Bn6JPgy9kL0V/Jw8I3usOzZ6gjpPud75b/jC+Je4LreHt2K2/7Ze9gA143VItS+0mPRDtDAznnNOcz9ysjJl8hqx0HGHMX6w9nCu8GewIK/Zr5JvS28D7vwuc+4rLeHtmC1NrQKs9uxqbB1rz6uBa3Lq4+qUqkVqNimnKVhpCmj9KHDoJefcZ5TnT2cMJsumjmZUJh2l6yW85VNlbqUPZTXk4iTU5M4kziTVpORk+uTZpQBlb2VnZafl8aYEJp/mxSdzZ6soLCi2aQnp5qpMazrrsmxyLTotym7iL4Gwp/FVMkizQjRBNUV2TjdbOGv5f7pWO678iT3kfs=', ('ricco', 3000): 'AABIBY4KzA8AFSYaOx87JCQp8i2iMjI3njvkPwFE9Ee6S1FPuFLtVe5YultRXrJg3GLOZIlmDWhaaXBqUWv8a3RsuGzLbK9sZGzta0xrgmqSaX9oSmf2ZYVk+2JZYaNf2l0CXB1aLVg1VjhUOFI3UDhOPExGSlhIckaYRMtCC0FaP7o9KzyuOkM57DeoNng1XDRTM10yejGqMOsvPi+gLhEukC0cLbMsVSz/K7EraCsjK+EqoSpgKh0q1imLKTkp3yh9KBAolycSJ4Am3iUtJW0kmyO4IsQhvSClH3sePx3xG5IaIhmiFxIWdBTHEg0RSA93DZ0LuwnRB+IF7gP3AQAACf4S/B76L/hF9mP0ifK48PPuOe2M6+7pXuje5m7lD+TB4oXhW+BD3zzeSN1l3JPb09oi2oDZ7thp2PDXg9ch18fWddYq1uPVoNVf1R/V3dSY1E/UAdSr003T5NJw0u/RYNHC0BXQVs+GzqPNrcyky4jKWMkUyL3GUsXVw0bCpsD1vjW9aLuOuai3urXEs8ixya/Irciry6nTp+Ol/qMmol2gp54FnXubCpq2mIGXbpZ+lbSUE5Sck1GTNZNIk4yTBJSvlJCVppbzl3eZMpsknU6fr6FGpBKnE6pIra+wRrQMuP+7HMBixM7IXs0O0tzWxdvF4NrlAOs08HL1uPo=', ('dispari', 3000): 'AAClBUcL3xBrFuYbTCGYJscr1TC/NYA6Fz+AQ7dHvEuKTyFTflagWYZcL1+aYcdjtmVnZ9toE2oOa9BrWmytbMtsuGx1bAVsbGurasdpw2ijZ2lmGWW4Y0hizmBNX8ldRVzEWktZ3Vd8VitV7lPHUrhRxFDsTzJPmE4fTshNk02CTZNNyE0fTphOMk/sT8RQuFHHUu5TK1V8Vt1XS1nEWkVcyV1NX85gSGK4YxllaWajZ8Nox2mramxrBWx1bLhsy2ytbFps0GsOaxNq22hnZ7Zlx2OaYS9fhlygWX5WIVOKT7xLt0eAQxc/gDq/NdUwxyuYJkwh5htrFt8QRwulBQAAW/q59CHvleka5LTeaNk51CvPQcqAxenAgLxJuES0drDfrIKpYKZ6o9GgZp45nEqamZgll+2V8pQwlKaTU5M1k0iTi5P7k5SUVZU5lj2XXZiXmeeaSJy4nTKfs6A3orujPKW1piOohKnVqhKsOa1IrjyvFLDOsGix4bE4sm2yfrJtsjiy4bFosc6wFLA8r0iuOa0SrNWqhKkjqLWmPKW7ozeis6Ayn7idSJznmpeZXZg9lzmWVZWUlPuTi5NIkzWTU5OmkzCU8pTtlSWXmZhKmjmcZp7RoHqjYKaCqd+sdrBEtEm4gLzpwIDFQcorzznUaNm03hrklekh77n0W/o=', ('fm_ferma', 3000): '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', ('dolce', 4500): 'AACjA0UH5QqBDhkSrBU4GbwcNyCoIw8naSq3LfcwKDRKN1o6Wj1HQCFD50WYSDRLu00qUINSxFTtVv1Y9FrSXJZeQGDQYUVjoGTgZQVnD2j/aNNpjmota7NrHmxvbKdsxmzLbLlsjmxLbPJrgmv8amFqsWntaBZoK2cuZiBlAmTTYpVhSWDuXoddFFyVWgxZeFfcVTdUi1LYUB5PYE2cS9VJCkg9Rm1EnULLQPo+KD1YO4k5vDfxNSk0ZDKjMOUuLC13K8cpHCh2JtUkOiOkIRQgiR4EHYUbCxqWGCcXvRVZFPkSnhFIEPYOqA1dDBYL0wmSCFQHGAbdBKUDbQI2AQAAyv6T/Vv8I/vo+az4bvct9ur0o/NY8grxuO9i7gftp+tD6tnoauf15Xvk/OJ34ezfXN7G3Cvbitnk1znWidTU0hvRXc+czdfLD8pEyHfGqMTYwgbBNb9jvZO7w7n2tyu2ZLSgsuKwKK91rcmrJKqIqPSma6Xso3miEqG3n2ueLZ3+m+Ca0pnVmOqXE5dPlp+VBJV+lA6UtZNyk0eTNZM6k1mTkZPik02U05RylS2WAZfxl/uYIJpgm7ucMJ7An2qhLqMMpQOnE6k8q32t1q9Fssy0aLcZut+8ub+mwqbFtsjYywnPSdKX1fHYWNzJ30TjyOZU6uftf/Eb9bv4Xfw=', ('ricco', 4500): 'AAD0A+gH2AvED6sTihdhGy8f8SKnJk4q5y1wMec0SzicO9c+/UEMRQNI4EqkTU5Q3FJOVaRX21n1W/Fdzl+LYSljp2QFZkNnYGhdaTpq9mqSaw9sbGypbMhsyGyqbG5sFWygaw9rY2qdab5oxWe1Zo5lUWT/YplhIGCVXvhcTFuRWchX8lURVCVSMFAyTi5MI0oSSP5F50POQbQ/mj2BO2o5VjdGNTozMzEzLzotSCtfKX8nqCXbIxkiYSC2HhUdgRv6GX4YEBeuFVoUEhPXEakQiA9zDmsNbgx+C5kKwAnxCCwIcgfABhgGeAXfBE4EwwM+A74CQgLKAVUB4gBwAAAAkP8e/6v+Nv6+/UL9wvw9/LL7IfuI+uj5QPmO+NT3D/dA9mf1gvSS85XyjfF48FfvKe7u7KbrUurw6ILnBuZ/5OviSuGf3+fdJdxY2oHYoda41MbSzdDNzsbMusqqyJbGf8RmwkzAMr4ZvAK67rfdtdKzzrHQr9ut76sOqjiob6a0pAija6Hgn2eeAZ2vm3KaS5k7mEKXY5adlfGUYJTrk5KTVpM4kziTV5OUk/GTbpQKlcaVo5agl72Y+5lZm9ecdZ4yoA+iC6QlplyosqokrbKvXLIgtf239LoDvinBZMS1xxnLkM4Z0rLVWdkP3dHgn+R26FXsPPAo9Bj4DPw=', ('dispari', 4500): 'AACrAlYFAAipClEN9g+ZEjkV1hdvGgQdlB8gIqckJyeiKRYshC7qMEkzoDXuNzQ6cTylPs9A70IFRRBHEEkFS+5My06cUGFSGVTEVWJX81h2WupbUV2pXvNfLmFZYnZjg2SBZW9mTmccaNtoiWknarRqMWuea/prRWyAbKpsw2zLbMNsqmyAbEVs+mueazFrtGonaolp22gcaE5nb2aBZYNkdmNZYi5h81+pXlFd6lt2WvNYYlfEVRlUYVKcUMtO7kwFSxBJEEcFRe9Cz0ClPnE8NDruN6A1STPqMIQuFiyiKScnpyQgIpQfBB1vGtYXORWZEvYPUQ2pCgAIVgWrAgAAVf2q+gD4V/Wv8grwZ+3H6irokeX84mzg4N1Z29nYXtbq03zRFs+3zGDKEsjMxY/DW8ExvxG9+7rwuPC2+7QSszWxZK+freerPKqeqA2niqUWpK+iV6ENoNKep52KnH2bf5qRmbKY5Jcll3eW2ZVMlc+UYpQGlLuTgJNWkz2TNZM9k1aTgJO7kwaUYpTPlEyV2ZV3liWX5JeymJGZf5p9m4qcp53Sng2gV6GvohakiqUNp56oPKrnq5+tZK81sRKz+7TwtvC4+7oRvTG/W8GPw8zFEshgyrfMFs980erTXtbZ2Fnb4N1s4PzikeUq6MfqZ+0K8K/yV/UA+Kr6Vf0=', ('fm_ferma', 4500): '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'}.items()}
RELEASE=binascii.a2b_base64('AAABAAUACwAUAB8ALQA9AFAAZQB8AJYAswDSAPMAFwE9AWYBkQG/Ae8BIQJWAo0CxwIDA0EDggPFAwsEUgScBOkENwWIBdwFMQaJBuMGPwedB/4HYQjGCC0JlgkBCm8K3gpQC8MLOQyxDCoNpg0jDqMOJA+oDy0QtBA9EcgRVBLiEnITBBSYFC0VxBVcFvYWkhcvGM4YbhkQGrMaWBv+G6YcTx35HaUeUh8AIK8gYCESIsUieSMuJOQknCVUJg0nyCeDKD8p/Cm6KnkrOSz5LLotfC4+LwIwxTCKMU8yFDPaM6A0ZzUuNvY2vjeGOE85GDrhOqo7dDw9PQc+0T6bP2RALkH4QcJCi0NVRB5F50WwRnlHQUgJSdFJmEpfSyVM60ywTXVOOk/9T8FQg1FFUgZTxlOGVEVVA1bAVnxXN1jyWKtZY1obW9Fbhlw6Xe1dn15QX/9frWBaYQZisGJZYwFkp2RMZe9lkWYxZ9BnbWgJaaNpO2rSamdr+2uNbB1tq203bsJuS2/Sb1dw23BccdxxWXLVck5zxnM8dK90IXWQdf51aXbSdjl3nncBeGJ4wHgceXZ5znkjend6yHoWe2N7rXv0ezp8fXy+fPx8OH1yfal93n0QfkB+bn6ZfsJ+6H4Mfy1/TH9pf4N/mn+vf8J/0n/gf+t/9H/6f/5//38=')
FM_ANIMATION=binascii.a2b_base64('CAgICQkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkICAgICAgHBwcHBwcGBgYGBgYGBgUFBQUFBQUFBQUFBQUFBQUFBQUFBQYGBgYGBgYGBwcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkICAgICAgHBwcHBwcGBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQYGBgYGBgYGBwcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkICAgICAgHBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQYGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkICAgICAgHBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkJCAgICAgHBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCwsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkJCAgICAgIBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQoKCgoKCgoKCgsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoJCQkJCQkJCAgICAgIBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQkKCgoKCgoKCgsLCwsLCwsLCwsLCwsLCwsLCwsLCgoKCgoKCgoKCQkJCQkJCAgICAgIBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwgICAgICAkJCQkJCQkKCgoKCgoKCgsLCwsLCwsLCwsLCwsLCwsLCwsLCwoKCgoKCgoKCQkJCQkJCAgICAgIBwcHBwcHBgYGBgYGBgYFBQUFBQUFBQUFBQUFBQUFBQUFBQUGBgYGBgYGBgcHBwcHBwcICAg=')


# ---- pcm_audio.py ----
"""Native wavetable renderer and bounded two-buffer hardware audio queue."""
import math,struct,time
try:import micropython
except ImportError:
    class micropython:
        @staticmethod
        def viper(f):return f

@micropython.viper
def render_native(dst,table,animation,release,n:int,step:int,phase:int,offset:int,total:int,asr:int,fm:int)->int:
    out=ptr16(dst);wave=ptr16(table);anim=ptr8(animation);env=ptr16(release)
    for i in range(n):
        age=i+offset
        frame=0
        if fm:
            ms=age//24
            if ms>1000:ms=1000
            frame=int(anim[ms])
        index=(phase>>16)&255;frac=phase&65535
        a=int(wave[frame*256+index]);b=int(wave[frame*256+((index+1)&255)])
        if a>=32768:a-=65536
        if b>=32768:b-=65536
        sample=a+(((b-a)*frac)>>16)
        gain=32767
        if asr:
            if age<24:gain=age*32767//24
            remain=total-1-age
            if remain<480:
                position=remain*255//480
                if position<0:position=0
                g=int(env[position])
                if g<gain:gain=g
        out[i]=(sample*gain)>>15
        phase=(phase+step)&16777215
    return phase

@micropython.viper
def render_sustain(dst,old_table,new_table,n:int,step_from:int,step_to:int,phase:int,glide:int,blend:int,initial:int)->int:
    out=ptr16(dst);old=ptr16(old_table);wave=ptr16(new_table)
    for i in range(n):
        index=(phase>>16)&255;frac=phase&65535
        a=int(wave[index]);b=int(wave[(index+1)&255])
        if a>=32768:a-=65536
        if b>=32768:b-=65536
        sample=a+(((b-a)*frac)>>16)
        if blend and i<glide:
            a=int(old[index]);b=int(old[(index+1)&255])
            if a>=32768:a-=65536
            if b>=32768:b-=65536
            previous=a+(((b-a)*frac)>>16)
            sample=previous+((sample-previous)*i)//glide
        if initial and i<24:sample=sample*i//24
        out[i]=sample
        step=step_to
        if i<glide:step=step_from+((step_to-step_from)*i)//glide
        phase=(phase+step)&16777215
    return phase

class PCMAudio:
    def __init__(self,speaker,settings):
        self.speaker=speaker;self.settings=settings;self.timbre='dolce';self.base_hz=1500
        self.master_volume=160;self.errors=0;self.calls=0;self.mode='silent';self.phase=0
        self.buffers=[None,None,None];self.slot=0;self.preview_until=0;self.max_render_us=0;self.underruns=0;self.update_gap=0;self.previous_update=None;self.loop_key=None;self.stream_started=False
        self.sustain_phase=0;self.sustain_step=None;self.sustain_table=None
        speaker.begin();speaker.setChannelVolume(0,255);speaker.setVolume(160)
    def set_volume(self,value,usb=False):
        value=max(0,min(int(value),255 if usb else 190))
        if value!=self.master_volume:self.master_volume=value;self.speaker.setVolume(value)
        if not value:self.stop()
    def stop(self):
        self.speaker.stop(0);self.mode='silent';self.preview_until=0
        self.buffers=[None,None,None];self.loop_key=None;self.stream_started=False
        self.sustain_phase=0;self.sustain_step=None;self.sustain_table=None
    def make_loop(self,hz):
        # Integer cycles and adjusted WAV rate give a closed periodic buffer.
        n=480;cycles=max(1,round(hz*n/24000));rate=round(hz*n/cycles)
        buf=bytearray(44+n*2)
        struct.pack_into('<4sI4s4sIHHIIHH4sI',buf,0,b'RIFF',36+n*2,b'WAVE',b'fmt ',16,1,1,rate,rate*2,2,16,b'data',n*2)
        band=next(b for b in (1800,3000,4500) if hz<=b)
        # Sustain has no envelope; FM keeps its rich stationary frame, no 100ms reset.
        render_native(memoryview(buf)[44:],AUDIO_TABLES[(self.timbre,band)],FM_ANIMATION,RELEASE,n,round(cycles*16777216/n),0,0,n,0,0)
        return buf
    def continuous_tone(self,v,sink):
        hz=max(150,min(4500,self.base_hz-250+45*v if sink else self.base_hz+180*v))
        queued=int(self.speaker.isPlaying(0))
        if self.stream_started and queued==0:self.underruns+=1
        # Two finite 120ms blocks, phase-continuous even when the requested pitch changes.
        # Never interrupt a playing buffer; control latency is bounded by queued audio.
        for _ in range(max(0,2-queued)):
            start=time.ticks_us();buf=self.make_sustain(hz)
            self.max_render_us=max(self.max_render_us,time.ticks_diff(time.ticks_us(),start))
            self.slot=(self.slot+1)%3;self.buffers[self.slot]=buf
            self.speaker.playWav(buf,1,0,False)
            self.loop_key=(sink,self.timbre);self.stream_started=True;self.calls+=1
    def make_sustain(self,hz):
        n=2880;rate=24000
        buf=bytearray(44+n*2)
        struct.pack_into('<4sI4s4sIHHIIHH4sI',buf,0,b'RIFF',36+n*2,b'WAVE',b'fmt ',16,1,1,rate,rate*2,2,16,b'data',n*2)
        band=next(b for b in (1800,3000,4500) if hz<=b)
        table=AUDIO_TABLES[(self.timbre,band)]
        previous=self.sustain_table if self.sustain_table is not None else table
        step=round(hz*16777216/rate)
        initial=self.sustain_step is None
        self.sustain_phase=render_sustain(memoryview(buf)[44:],previous,table,n,
            step if initial else self.sustain_step,step,self.sustain_phase,192,int(previous is not table),int(initial))
        self.sustain_step=step;self.sustain_table=table
        return buf
    def make_wav(self,v,slow,kind,continuous=False):
        hz=max(150,min(4500,self.base_hz+180*v))
        if continuous:
            hz=max(150,min(4500,self.base_hz-250+45*v));period=.10;segments=[(.10,hz,False)]
        elif kind=='continuous':
            segments=[(.10,hz,False)];period=.10
        elif kind in ('curves','pair'):
            f,length,pause=curve(v);hz=max(150,min(4500,f+self.base_hz-500))
            if kind=='pair':
                second=max(150,min(4500,curve(v+.5)[0]+self.base_hz-500))
                segments=[(length,hz,True),(.04,0,False),(length,second,True),(pause,0,False)]
                period=2*length+.04+pause
            else:segments=[(length,hz,True),(pause,0,False)];period=length+pause
        else:
            period=max(.12,.65/(1+max(v,0)*1.4));duty=.50 if kind=='dualmean' else .45
            if kind=='dualmean':
                second=max(150,min(4500,self.base_hz+180*(slow if slow is not None else v)))
                segments=[(period*duty/2,hz,True),(period*duty/2,second,True),(period*(1-duty),0,False)]
            else:segments=[(period*duty,hz,True),(period*(1-duty),0,False)]
        counts=[round(d*24000) for d,_,_ in segments];size=sum(counts)*2
        buf=bytearray(44+size)
        struct.pack_into('<4sI4s4sIHHIIHH4sI',buf,0,b'RIFF',36+size,b'WAVE',b'fmt ',16,1,1,24000,48000,2,16,b'data',size)
        start=0;offset=0;total_on=sum(counts[:-1]) if kind=='dualmean' and not continuous else 0
        for count,(_,freq,asr) in zip(counts,segments):
            if freq:
                band=next(b for b in (1800,3000,4500) if freq<=b)
                phase=render_native(memoryview(buf)[44+start*2:44+(start+count)*2],AUDIO_TABLES[(self.timbre,band)],FM_ANIMATION,RELEASE,count,
                                    int(freq*16777216/24000),self.phase,offset if total_on else 0,total_on or count,int(asr),int(self.timbre=='fm_ferma'))
                self.phase=phase;offset+=count
            start+=count
        return buf
    def submit(self,v,slow,kind,continuous=False,replace=False):
        start=time.ticks_us();buf=self.make_wav(v,slow,kind,continuous)
        self.max_render_us=max(self.max_render_us,time.ticks_diff(time.ticks_us(),start))
        self.slot=(self.slot+1)%3;self.buffers[self.slot]=buf
        self.speaker.playWav(buf,1,0,replace);self.calls+=1
    def preview(self,now):
        self.stop()
        if self.master_volume:
            self.submit(1.,1.,'classic',replace=True);self.preview_until=now+300
    def update(self,now,v,slow,kind,enabled):
        if self.previous_update is not None:self.update_gap=max(self.update_gap,now-self.previous_update)
        self.previous_update=now
        if now<self.preview_until:return
        if not enabled or v is None:
            if self.mode!='silent':self.stop()
            return
        c=self.settings
        mode='climb' if v>=(c['climb_off'] if self.mode=='climb' else c['climb_on']) else 'sink' if v<=(c['sink_off'] if self.mode=='sink' else c['sink_on']) else 'silent'
        if mode!=self.mode:self.stop();self.mode=mode
        if mode=='silent':return
        if mode=='sink' or kind=='continuous':
            try:self.continuous_tone(v,mode=='sink')
            except Exception as e:self.errors+=1;self.stop();print('E,PCM,%s'%e)
            return
        if self.loop_key is not None:self.stop();self.mode=mode
        queued=int(self.speaker.isPlaying(0))
        if self.stream_started and queued==0:self.underruns+=1
        if queued<2:
            try:self.submit(v,slow,kind);self.stream_started=True
            except Exception as e:self.errors+=1;self.stop();print('E,PCM,%s'%e)


# ---- configuration.py ----
"""Versioned configuration; no writes except an explicit save request."""
import json,math
FILTERS=('kal','reg','lp','dual','sky')
SOUNDS=('dolce','ricco','dispari','fm_ferma')
PATTERNS=('classic','continuous','dualmean','curves','pair')
CONFIG_PATH='/flash/stick_vario_config_v1.json'

def defaults():
    return {'filters':list(FILTERS),'sounds':list(SOUNDS),'volumes':[0,64,110,160,190,220,255],
            'base_notes':[1000,1250,1500,1750,2000,2250,2500],'patterns':list(PATTERNS),'remote_hid':False,'grove_buttons':False,
            'base_hz':1500,'pattern':'classic','climb_on':.10,'climb_off':.06,'sink_on':-.50,'sink_off':-.30}

def validate(value):
    if not isinstance(value,dict):raise ValueError('configuration keys')
    # Migrate v1 settings saved before external buttons, preserving all old values.
    value=dict(value)
    for key in ('base_notes','patterns','remote_hid','grove_buttons'):
        if key not in value:value[key]=defaults()[key]
    if set(value)!=set(defaults()):raise ValueError('configuration keys')
    out={}
    for key,allowed in (('filters',FILTERS),('sounds',SOUNDS),('patterns',PATTERNS)):
        a=value[key]
        if not isinstance(a,list) or not a or len(a)>len(allowed) or len(set(a))!=len(a) or any(x not in allowed for x in a):raise ValueError(key)
        out[key]=list(a)
    a=value['base_notes']
    if not isinstance(a,list) or not a or len(a)>16 or any(type(x)!=int or not 550<=x<=2500 for x in a) or len(set(a))!=len(a):raise ValueError('base_notes')
    out['base_notes']=list(a)
    if type(value['remote_hid'])!=bool:raise ValueError('remote_hid')
    out['remote_hid']=value['remote_hid']
    if type(value['grove_buttons'])!=bool:raise ValueError('grove_buttons')
    out['grove_buttons']=value['grove_buttons']
    a=value['volumes']
    if not isinstance(a,list) or not a or len(a)>12 or any(type(x)!=int or x<0 or x>255 for x in a) or a!=sorted(set(a)) or a[0]!=0:raise ValueError('volumes: sorted, unique, include mute0')
    out['volumes']=list(a)
    if type(value['base_hz'])!=int or not 550<=value['base_hz']<=2500:raise ValueError('base_hz')
    out['base_hz']=value['base_hz']
    if value['pattern'] not in PATTERNS:raise ValueError('pattern')
    out['pattern']=value['pattern']
    for key in ('climb_on','climb_off','sink_on','sink_off'):
        v=value[key]
        if type(v) not in (int,float) or not math.isfinite(v) or abs(v)>10:raise ValueError(key)
        out[key]=float(v)
    if not 0<=out['climb_off']<out['climb_on']<=5:raise ValueError('climb hysteresis')
    if not -10<=out['sink_on']<out['sink_off']<=0:raise ValueError('sink hysteresis')
    return out

def load_config(path=CONFIG_PATH):
    try:
        with open(path) as f:doc=json.load(f)
        if doc['v']!=1:raise ValueError('version')
        return validate(doc['config']),None
    except OSError:return defaults(),None
    except Exception as e:return defaults(),str(e)

def save_config(config,path=CONFIG_PATH):
    import os
    doc={'v':1,'config':validate(config)}
    with open(path+'.tmp','w') as f:f.write(json.dumps(doc))
    # Targeted application settings only; never touches system startup files.
    getattr(os,'replace',os.rename)(path+'.tmp',path)

def schema():
    return {'filters':list(FILTERS),'sounds':list(SOUNDS),'patterns':list(PATTERNS),
            'base_notes':[550,2500],'remote_hid_restart':True,'base_hz':[550,2500],'volume':[0,255],'battery_volume_max':190}

class ConfigProtocol:
    def __init__(self,apply,preview,initial=None,path=CONFIG_PATH):
        self.config=validate(initial or defaults());self.apply=apply;self.preview=preview;self.path=path;self.saved=False
        try:
            with open(path) as f:doc=json.load(f)
            self.saved=doc.get('v')==1 and validate(doc['config'])==self.config
        except Exception:pass
    def handle(self,request):
        ident=request.get('id') if isinstance(request,dict) else None
        response={'v':1,'id':ident}
        try:
            if not isinstance(request,dict) or request.get('v')!=1 or type(ident)!=int or not 0<=ident<=2147483647:raise ValueError('protocol v/id')
            op=request.get('op')
            if op=='get':pass
            elif op=='set':
                new=validate(request['config']);self.apply(new);self.config=new;self.saved=False
            elif op=='reset':
                new=defaults();self.apply(new);self.config=new;self.saved=False
            elif op=='save':
                if not self.saved:save_config(self.config,self.path)
                self.saved=True
            elif op=='preview':
                sound=request.get('sound')
                if sound not in SOUNDS:raise ValueError('sound')
                self.preview(sound)
            else:raise ValueError('operation')
            response.update({'ok':True,'config':self.config,'schema':schema(),'saved':self.saved})
        except Exception as e:response.update({'ok':False,'error':str(e)[:140]})
        return response


# ---- ble_link.py ----
"""BLE NUS telemetry plus standard battery and temperature read/notify services."""
import struct

def lk8_sentence(p,tc,v,battery):
    # Pressure/vario keep conventional integer units; temperature retains one decimal.
    body = 'LK8EX1,%d,99999,%d,%.1f,%d,' % (round(p),round(v*100),tc,1000+battery if battery is not None else 999)
    crc=0
    for c in body: crc^=ord(c)
    return ('$%s*%02X\r\n' % (body,crc)).encode()

CFG_SERVICE='a50e0001-2d94-4c9a-983d-1abf4300c001'
CFG_TX='a50e0002-2d94-4c9a-983d-1abf4300c001'
CFG_RX='a50e0003-2d94-4c9a-983d-1abf4300c001'

class BLELink:
    def __init__(self,bluetooth,remote_hid=False):
        self.ble=bluetooth.BLE()
        self.ble.active(False)
        # NimBLE requests identity/bond secrets during active(True), before GATT.
        self.remote=RemoteHID() if remote_hid else None
        self.ble.irq(self._irq)
        if self.remote:self.remote.configure(self.ble)
        self.ble.active(True)
        self.ble.config(gap_name='StickVario')
        U=bluetooth.UUID
        nus=U('6e400001-b5a3-f393-e0a9-e50e24dcca9e')
        tx=U('6e400003-b5a3-f393-e0a9-e50e24dcca9e')
        rx=U('6e400002-b5a3-f393-e0a9-e50e24dcca9e')
        services=((nus,((tx,0x12),(rx,0x0C))),
                  (U(0x180F),((U(0x2A19),0x12),)),
                  (U(0x181A),((U(0x2A6E),0x12),)),
                  (U(CFG_SERVICE),((U(CFG_TX),0x12),(U(CFG_RX),0x08))))
        if self.remote:
            services=services+(self.remote.service(U),(U(0x180A),((U(0x2A29),2),(U(0x2A24),2),(U(0x2A50),2))))
        handles=self.ble.gatts_register_services(services)
        ((self.tx,self.rx),(self.batt_handle,),(self.temp_handle,),(self.cfg_tx,self.cfg_handle))=handles[:4]
        if self.remote:
            self.remote.bind(self.ble,handles[4])
            manufacturer,model,pnp=handles[5]
            self.ble.gatts_write(manufacturer,b'DIY StickVario')
            self.ble.gatts_write(model,b'M5StickS3')
            # Prototype PnP identification follows the board's observed USB VID/PID.
            self.ble.gatts_write(pnp,struct.pack('<BHHH',2,0x303A,0x832B,1))
        # Reapply after native startup/GATT setup as well as before active(True).
        # Cold startup must not depend on security state left by a prior RAM run.
        if self.remote:self.remote.configure(self.ble)
        # Service registration may reset the built-in GAP name. Set it last.
        self.ble.config(gap_name='StickVario')
        self.ble.gatts_set_buffer(self.rx,128,False)
        self.ble.gatts_set_buffer(self.cfg_handle,1024,True)
        self.cfg_rx=b'';self.cfg_pending=b''
        self.connections=set()
        self.advertise_pending=True
        self.pending=b''
        self.rx_pending=b''
        self.errors=self.messages=self.chunks=0
        self.last_meta=-5000
        self.adv=b'\x02\x01\x06'+bytes((17,0x07))+bytes(nus)
        if self.remote:self.adv+=b'\x03\x03\x12\x18\x03\x19\xc1\x03'
        name=b'StickVario'
        self.resp=bytes((len(name)+1,0x09))+name
        self.ble.irq(self._irq)
        self.pump()
    def _irq(self,event,data):
        if self.remote and event in (28,29,30,31):return self.remote.irq(event,data)
        if event==1:self.connections.add(data[0])
        elif event==2:
            if self.remote:self.remote.disconnect(data[0])
            self.connections.discard(data[0]);self.pending=b'';self.cfg_pending=b'';self.cfg_rx=b'';self.advertise_pending=True
        elif event==3 and data[1]==self.cfg_handle:
            data=self.ble.gatts_read(self.cfg_handle)
            if len(self.cfg_rx)+len(data)<=2048:self.cfg_rx+=data
            else:self.errors+=1;self.cfg_rx=b''
        elif event==3 and data[1]==self.rx:
            self.rx_pending=self.ble.gatts_read(self.rx)[:128]
    def config_reply(self,line):
        data=(line+'\n').encode()
        if len(data)<=2048:self.cfg_pending=data
        else:self.errors+=1
    def pump(self):
        if self.advertise_pending:
            self.advertise_pending=False
            self.ble.gap_advertise(250000,adv_data=self.adv,resp_data=self.resp)
        if self.cfg_pending and self.connections:
            piece=self.cfg_pending[:20]
            for conn in tuple(self.connections):
                try:self.ble.gatts_notify(conn,self.cfg_tx,piece)
                except OSError:self.errors+=1
            self.cfg_pending=self.cfg_pending[20:]
        if self.pending and self.connections:
            piece=self.pending[:20]
            for conn in tuple(self.connections):
                try:self.ble.gatts_notify(conn,self.tx,piece);self.chunks+=1
                except OSError:self.errors+=1
            self.pending=self.pending[20:]
    def publish(self,now,p,tc,v,battery):
        if self.connections and not self.pending:
            self.pending=lk8_sentence(p,tc,v,battery)
            self.messages+=1
        if now-self.last_meta>=1000:
            self.last_meta=now
            temp=struct.pack('<h',max(-32768,min(32767,round(tc*100))))
            self.ble.gatts_write(self.temp_handle,temp)
            b=bytes((battery,)) if battery is not None else None
            if b is not None:self.ble.gatts_write(self.batt_handle,b)
            for conn in tuple(self.connections):
                try:
                    self.ble.gatts_notify(conn,self.temp_handle,temp)
                    if b is not None:self.ble.gatts_notify(conn,self.batt_handle,b)
                except OSError:self.errors+=1
    def remote_page(self):
        return bool(self.remote and self.remote.click())
    def close(self):
        if self.remote:self.remote.close()
        for conn in tuple(self.connections):
            try:self.ble.gap_disconnect(conn)
            except OSError:pass
        self.ble.gap_advertise(None)


# ---- splash_audio.py ----
# Generated by make_splash_audio.py; original synthesized audio.
import binascii
def startup_wav():
    return binascii.a2b_base64(
        'UklGRmQAAQBXQVZFZm10IBAAAAABAAEAgD4AAIA+AAABAAgAZGF0YUAAAQCAgYWHh4eDf3ZyaWRpdpmlpqCUjXpxZV9WWn2Tqqmd'
        'l4l/bmhcV19xm6emoJWOe3JlX1ZZepCpqZ6YioFvaV1XXm6Ypqehlo98c2ZgVlh3jampn5mLgnBpXlhca5akqKKWkH50Z2FWWHSK'
        'qKqfmoyDcWpeWVtpk6Ooo5eRf3VoYldXcYenqqCajoVya19ZWmaQoamkmJKAd2hjV1ZuhKaqoZuPhnNsYFpYZI6gqaWZk4J4aWRY'
        'VmyBpaqinJCHdG1hW1hii56qpZmUg3lqZFhWaX6jqqOdkYh1bmJcV2CIm6qmmpSEemtlWVZne6KppJ2SinZuY1xXXoWZqqeblYZ8'
        'bGZaVmR4oKmknpOLeG9jXVZdgpeqqJyWh31sZ1tWYnWeqKWfk4x5cGReVlt/lKqonZeIfm1nW1dgcpynpqCUjXpxZV9WWnyRqqmd'
        'mImAbmhcV15vmqanoZWOfHNmYFZZeY+pqZ6Yi4FvaV1YXW2Xpaiilo99dGZhVlh2jKiqn5mMg3BqXlhbapWkqKOXkH51Z2FXV3OJ'
        'qKqgmo2EcWpfWVpokqKpo5iRgHZoYldXcIanqqGbjoVya2BaWWWPoamkmJKBd2ljV1Ztg6WqopuPhnNsYFpYY4yfqqWZk4J4amRY'
        'VmuApKqinJCIdW1hW1dhiZ2qppqUhHpqZVlWaH2jqqOdkYl2bmJcV1+Gmqqnm5WFe2tlWVZmeqGppJ6SindvY11WXYOYqqebloZ8'
        'bGZaVmN3n6mln5OLeHBkXlZcgJWqqJyWiH5tZ1tWYXSdqKaglI16cWVeVlt9k6qpnZeJf25oXFdfcZunpqCVjntyZV9WWXqQqame'
        'mIqAb2hdV15umKanoZWPfHNmYFZYd42pqZ+Zi4JwaV1YXGuWpaiilpB9dGdhVlh0iqiqn5qMg3FqXlhbaZOjqKOXkX91aGJXV3GH'
        'p6qgmo2EcmtfWVpmkaKppJiSgHdoY1dWb4SmqqGbj4ZzbGBaWWSOoKmlmZOCeGljWFZsgaWqopyQh3RtYVtYYoueqqWZlIN5amRY'
        'Vml+o6qjnZGIdW1iXFdgiJyqppqUhHprZVlWZ3uiqaSdkop2bmNcV16Fmaqnm5WGfGxmWlZleKCppJ6Si3hvY11WXYKXqqiclod9'
        'bGdbVmJ1nqiln5OMeXBkXlZbf5SqqJyXiH5tZ1tXYHKcqKaglI16cWVfVlp8kqqpnZiJgG5oXFdfcJqnp6GVjntyZmBWWXmPqame'
        'mIuBb2ldWF1tl6WnopaPfXRmYVZYdoyoqp+ZjIJwal5YXGqVpKiil5B+dWdhV1dziaiqoJqNhHFqX1laaJKiqaOXkX92aGJXV3CG'
        'p6qhm46FcmtgWlllj6GppJiSgXdpY1dWbYOmqqGbj4ZzbGBaWGONn6qlmZOCeGlkWFZrgKSqopyQiHRtYVtXYYqdqqaalIN6amVZ'
        'Vmh9o6qjnZGJdm5iXFdfh5uqppqVhXtrZVlWZnqhqaSekop3b2NdVl6EmKqnm5aGfGxmWlZkd5+ppZ+Ti3hwZF5WXIGWqqiclod+'
        'bWdbVmJ0naimn5SMeXFkXlZbfpOqqJ2XiX9uaFxXYHGbp6aglY57cmVfVlp6kKmpnpiKgG9oXVdebpmmp6GVj3xzZmBWWHeOqame'
        'mYuCcGldWFxslqWoopaQfXRnYVZYdYuoqp+ZjINxal5YW2mUo6ijl5F/dWhiV1dyiKeqoJqNhHJrX1laZ5GiqaSYkoB2aGNXV2+F'
        'pqqhm46Gc2xgWllkjqCppJmTgXhpY1hWbIKlqqKcj4d0bGFbWGKLnqqlmZODeWpkWFZqf6Sqo52QiHVtYltXYIicqqaalIR6a2VZ'
        'Vmd8oqqknZGJdm5iXFdfhZqqp5uVhXxrZlpWZXmgqaSekot3b2NdVl2Cl6qonJaHfWxmWlZjdp6opZ+TjHlwZF5WW3+Vqqicl4h+'
        'bWdbV2FznKimoJSNenFlX1ZafJKqqZ2YiYBuaFxXX3Cap6ehlY57cmZgVll5j6mpnpiKgW9pXVddbZilp6GWj31zZmBWWHaMqaqf'
        'mYyCcGpeWFxrlaSoopeQfnVnYVZXc4moqqCajYRxal9ZWmiSo6mjl5F/dmhiV1dwhqeqoJuOhXJrX1lZZpChqaSYkoF3aWNXVm6D'
        'pqqhm4+Gc2xgWlhjjZ+qpZmTgnhpZFhWa4CkqqKckIh0bWFbWGKKnaqlmZSDemplWVdpfaKpopyQiXZuY11YYYeaqKWZlIR7bGdc'
        'WWh7n6ahm5CJeHBlYFthg5alo5iThX1ual9caHmbo5+akIl5c2lkXmOBkqGglpKGfnFtZGBpd5aenJeOiXt1bGhiZn6NnZyTkIZ/'
        'dHBoZWx3kZiYlI2IfXhwbWdqfYqXl5CNhYB3dG1rb3eNk5OQiod+enRxbW58hpKSjYqFgXl3cnByeIiOj4yIhn98d3Zyc3yDjI2K'
        'iISBfHp3dXZ6hYmKiYWEgH57eXd3fYKIiIaFgoF9fHp5enyDhYaFg4KAf318e3t+gYSEg4OBgX9+fX19foGCg4KCgYB/f35+fn+A'
        'goKBgYGAgH9/f39/gIGBgYCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgIB9e3Z0eICSl5WTjIV1bmBaWWSOoKmkmJKAdmhiV1dyiKiqoJqMg3BqXlhca5al'
        'p6KWj3xzZmBWWXqQqamdl4l/bmdbV2F0nailn5OMeHBjXVZdg5iqp5uVhXtrZVlWZ3yjqqOdkIh1bWFbWGKMn6qlmZOBd2ljV1Zv'
        'haeqoJqNhHFqX1lbaZSkqKKWkH10ZmBWWHiOqamemIqAbmhcV19xm6emoJSNeXFkXlZcgZaqqJyWhnxsZlpWZXqhqaSdkYl2bmJc'
        'V2GJnaqlmZOCeGlkWFZtg6aqoZuOhXJrX1laZ5KiqaOXkX51Z2FWWHWLqKqfmYuBb2ldV15vmaanoZWOenFlX1ZbfpSqqJyXh31s'
        'Z1pWZHegqaSekop3b2JcV1+Hm6qmmpSEempkWFZqgKSqopyPhnNsYFpZZY+hqaSYkYB2aGJXV3OJqKqfmYyDcGleWF1sl6WnoZWO'
        'fHJlX1Zae5GqqZ2XiH9tZ1tWYnWeqKWfk4t4b2NdVl6Emaqnm5WFe2tlWVZofaOqo5yQiHRtYVtYY42fqaSYkoF3aGNXV3CGp6qg'
        'mo2EcWpeWFtqlaSoopaPfXNmYFZZeY+pqZ6YioBuaFxXYHKcqKaglIx5cGReVlyCl6qnm5aGfGtmWVZme6Kqo52RiXVtYltXYYqe'
        'qqWZk4J4aWNYVm6Epqqhm46FcmtfWVpok6Ooo5eQfnRnYVZYdoypqZ6Zi4FvaV1XXnCap6aglI16cWVeVlt/laqonJaHfWxmWlZk'
        'eKCppJ6SinZuYlxXYIicqqaalIN5amRYVmuBpaqim4+Gc2xgWllmkKKpo5eRf3VnYldXc4qoqp+ZjIJwaV1YXW2YpqehlY57cmVf'
        'Vlp8kqqonZeIfm1nW1Zidp+ppZ6Ti3dvY11WXoWaqqealYR6amVZVml+pKqinJCHdGxhWlhkjqCppJiSgHZoYldXcYenqqCajYNx'
        'al5YXGuWpaiilo98c2ZgVll6kKmpnZiJf25oXFdhc52opZ+TjHhwZF1WXYOYqqeblYV7a2VZVmd8oqqjnZGIdW1hW1hii56qpZmT'
        'gXhpY1dWb4WmqqGbjoRya19ZW2mUo6iil5B9dGdhVlh3jampnpiKgG9oXFdfcZunpqCUjXpxZF5WW4CVqqicloZ9bGZaVmV5oamk'
        'npGJdm5iXFdgiZyqppmUg3lqZFhWbIKlqqGbj4Zya19ZWmeRoqmjl5F/dWdhVlh0i6iqn5mLgm9pXVdebpmmp6GVjntyZV9WWn2T'
        'qqicl4h+bWdbVmN3n6mknpKKd29jXFdfhpuqppqUhHpqZFhWan+kqqKcj4dzbGBaWWWPoamkmJKAdmhiV1dyiKiqoJqMg3BqXlhc'
        'bJelp6GWj3xzZmBWWXuRqqmdl4l/bWdbVmF0nqiln5OLeHBjXVZdhJiqp5uVhXtrZVlWaH2jqqOdkIh0bWFbWGOMn6mlmZKBd2lj'
        'V1dwhqeqoJqNhHFqXllbapWkqKKWkH10ZmBWWHiOqamemIqAbmhcV2BxnKemoJSMeXBkXlZcgZaqqJuWhnxsZlpWZnqhqaOdkYl1'
        'bmJbV2GKnaqlmZOCeGljWFZtg6aqoZuOhXJrX1laZ5KjqKOXkH51Z2FWWHWMqaqfmYuBb2ldV15vmqenoJWNenFlX1ZbfpSqqJyW'
        'h31sZlpWZHigqaSekop2bmJcV1+Hm6qmmpSDeWpkWFZrgKWqopyPhnNsYFpZZZChqaSYkX92aGJXV3OJqKqfmYyCcGldWF1tmKan'
        'oZWOe3JlX1ZafJKqqZ2XiH5tZ1tWYnWeqKWfk4t4b2NdVl6Fmaqnm5WEemtlWVZpfqOqopyQh3RtYVpYY42gqaSYkoF3aGNXV3CH'
        'p6qgmo2EcWpeWFtqlaSoopaPfXNmYFZZeY+pqZ6YiYBuaFxXYHKcqKaflIx5cGReVlyCl6qnm5WGfGtmWVZne6Kqo52RiXVtYVtX'
        'YoueqqWZk4J4aWNXVm6Epqqhm46FcmtfWVpok6Ooo5eQfnRnYVZYdo2pqZ6YioFvaFxXX3Cap6aglI16cWReVlt/laqonJaHfWxm'
        'WldleaCpo52RiXZvY11YYYibqKSZk4N5a2VaWG2Bo6efmo6FdG1iXV1oj5+loJWPf3ZqZVxcdYmjpJuVioJybWNeY3GUn6CbkYt8'
        'dWtmX2J9jqCflpGGfnJtZWJreZadmpWNh3p0bGhkaoSRm5mRjYN8cm9oZnJ/lZmUkImEeXVua2pxiJGWk4yJgHt0cWxseYSSlI+M'
        'hoF5dnFvcXeJj5CNiIZ/e3Z0cXJ+ho6OioiDgHp4dXN3fIiLiomFg358eXd2eIGGiomGhYF/fHt4eHt/hoeGhYOBfn17e3p8goSF'
        'hYOCgH99fXx8foGEhIOCgYB/fn59fX6BgoKCgYGAf39/fn6AgIGBgYGAgIB/f39/gICBgYCAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgoSEgn95dW1pcX6boZ6ZjoVya15YXGyYpqaglIx4cGNdV1+InaqlmZKAdmhiVlh3jqmpnZeIfmxmWlZnfKOq'
        'opyPhnJrX1hca5imp6CUjXlwY11WX4ecqqWZk4F3aGJXV3aNqamdl4h+bWZaVmZ7o6qinI+GcmtfWVtrl6WnoZSNeXBkXVZehpuq'
        'ppmTgXdoYldXdYypqZ6YiX9tZ1pWZXqiqqOcj4Zza19ZW2qWpaehlY16cWReVl6FmqqmmZOCd2hiV1d0i6mpnpiJf21nWlZleaKq'
        'o5yQh3NsX1laaZWlp6GVjnpxZF5WXYSaqqaak4J4aWNXV3OKqKqemIp/bWdbVmR4oamjnZCHc2xgWVpolKSoopWOe3FkXlZdhJmq'
        'ppqUgnhpY1dXcomoqp6YioBuZ1tWY3ehqaOdkIh0bGBaWmeTpKiilo57cmVeVlyDmKqnmpSDeWljV1dxiKiqn5mKgG5oW1ZjdqCp'
        'pJ2RiHRsYFpZZ5OjqKKWj3tyZV9WXIKXqqealIN5aWNXVnCHqKqfmYuBbmhcV2J2n6mknZGIdG1gWllmkqOoopaPfHJlX1ZbgZeq'
        'p5uVhHlqZFhWb4anqp+Zi4FvaFxXYXWfqaSekYl1bWFaWWWRoqijlo98c2VfVluAlqqnm5WEempkWFZuhaeqn5mLgm9oXFdhdJ6p'
        'pJ6SiXVtYVtYZJCiqaOXkH1zZl9WWn+VqqeblYV6amRYVm6Ep6qgmoyCb2lcV2BznqilnpKKdm5hW1hkj6Gpo5eQfXNmYFZafpSq'
        'qJuVhXtqZFhWbYOmqqCajIJwaV1XX3KdqKWekop2bmJbWGOOoamjl5B+dGZgVlp9k6qonJaFe2tlWFZsgqaqoJqNg3BpXVdfcZyo'
        'pZ+SinZuYltYYo2gqaSXkX50ZmBWWXySqqicloZ7a2VZVmuBpqqhmo2DcGldV15wm6iln5OLd25iXFdijJ+ppJiRfnVnYVZZe5Kq'
        'qJyWhnxrZVlWaoClqqGbjYRxal1YXm+bp6afk4t3b2JcV2GLn6mkmJF/dWdhVll6kaqonJaHfGtlWVZpf6WqoZuOhHFqXlhdbpqn'
        'pqCTjHhvY1xXYYqeqaSYkn91Z2FWWHmQqqmdl4d9bGZZVml+pKqhm46FcWpeWF1tmaemoJSMeG9jXFdgip2qpZiSgHZnYVZYeI+p'
        'qZ2Xh31sZllWaH2kqqKbjoVyal5YXG2ZpqaglIx4cGNdV1+JnaqlmZKAdmhiVlh3jqmpnZeIfmxmWlZnfKOqopyPhXJrXlhcbJim'
        'p6CUjXlwY11XX4icqqWZk4F2aGJWWHaNqamdl4h+bWZaVmZ8o6qinI+GcmtfWVtrl6anoZSNeXBkXVZeh5uqppmTgXdoYldXdYyp'
        'qZ6YiX5tZ1pWZnuiqqKcj4Zza19ZW2qWpaehlY16cWRdVl6Gm6qmmZOBd2hiV1d0i6mpnpiJf21nWlZleqKqo5yQh3NsX1lbaZWl'
        'p6GVjnpxZF5WXYWaqqaak4J4aWNXV3OKqKmemIl/bWdbVmR5oaqjnZCHc2xgWVpolaSooZWOenFkXlZdhJmqppqUgnhpY1dXcomo'
        'qp6YioBuZ1tWY3ihqaOdkIh0bGBaWmiUpKiilY57cmVeVlyDmKqmmpSDeGljV1dxiKiqn5mKgG5oW1Zjd6CppJ2RiHRsYFpZZ5Oj'
        'qKKWj3tyZV9WXIKYqqealIN5aWNXVnCHqKqfmYuBbmhbV2J2oKmknZGIdG1gWllmkqOoopaPfHJlX1ZbgZeqp5qUhHlqZFhWcIan'
        'qp+Zi4FvaFxXYXWfqaSekYl1bWFaWWaRoqiilo98c2ZgV1yAlqmmmpSEemtlWVhvhaWonpiLgXBqXlljdZymoZuQiHZvZF5daI6e'
        'pJ+Ujn11aWRcYH+SpKGXkoR7bmlfXnGEn6KZlImCc25kYWh2lp6blo2HeHNqZWRsi5ecmJCLfnhva2Rnf42bmZGNg31zb2hndYKW'
        'mJKPh4F3c21qb3mPlZOPiYV7d3FubXOHj5OQiod/e3Vzb3B/iJCPioiCfnh2cnF5gY2Oi4iEgXt5dXR3fIiLioiFg357eHd2eYOH'
        'iYiFhIB+e3p4eX+Dh4eFhIF/fXx6en2AhYWEg4KAfn18fH1+g4SDg4KBf39+fX1+gYKCgoGBgH9/f35+gIGBgYGBgIB/f39/gICB'
        'gYCAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBgYB7eHFudYCYnJiUioFvaFtWZHiiqqKcj4Vxal5YXnCdqKWe'
        'kYl0bGBZWmmWpaeglIx4b2JcWGOPoamjlo97cmReVl6HnKqlmJJ/dWdgVlp+laqnmpSDeGljV1d2jqmpnZaGfGtlWFZuhaeqn5mK'
        'f21nWlZnfaSqoZuNg3BpXFdhdaCpo52Qh3NrX1hcbZqnpp+TinZuYVpZZpOkqKGVjXlwY11XYIufqaSXkH1zZV9WXIOZqqaZk4F2'
        'Z2FWWHqSqqiblYR6amRXV3KKqamel4h9bGZZVmuCpqqgmouBbmhbVmR5oqqinI6FcWpdV19xnaiknpGIdGxgWVtql6anoJSMd29i'
        'W1hjj6KoopaPe3FkXlZeh5yqpZiSf3VmYFZaf5aqp5qUgnhoYldXd46pqZyWhntrZVhWb4aoqp+YiX9tZ1pWaH6lqqGbjYNwaVxX'
        'YnWgqaOdkIdya15YXW6ap6Wfkop2bWFaWWeTpKehlY15cGNcV2GMn6mkl5B9c2VfVlyDmaqmmZOAdmdhVll7kqqom5WEemljV1dz'
        'iqmpnZeIfWxmWVZrgqaqoJmLgW5oW1ZleqOqopuOhXFqXVdfcp6opJ6RiHRsYFlbapempqCTi3dvYltYZJCiqKKWj3txZF5WXoid'
        'qqWYkX50ZmBWWoCWqqealIJ4aGJXWHePqqmcloZ7amRYVm+HqKqemIl/bWZaVmh+paqhmoyDb2lcV2J2oKmjnI+GcmteWF1um6el'
        'n5KKdW1hWllnlKSnoZWNeXBjXFdhjKCpo5eQfHNlX1ZchJqqppmSgHZnYVZZfJOqqJuVhHlpY1dXdIupqZ2Xh31rZVlWbIOnqp+Z'
        'i4FuZ1tWZXujqqKbjoRxal1XYHKeqaSdkYh0bF9ZW2uYpqagk4t3bmJbWGSRoqiilo56cWRdVl+JnamkmJF+dGZgVluAl6qnmpSC'
        'd2hiVlh4j6qonJaFe2pkWFZwh6iqnpiJf21mWlZpf6WqoJqMgm9oXFdid6Gpo5yPhnJrXlhdb5uopZ+SiXVtYFpaaJWlp6GUjXhw'
        'Y1xXYo2gqaOXkHxyZV5WXYWaqqWZkoB2Z2FWWXyTqqeblYN5aWNXV3SMqamdl4d9a2VZVm2Ep6qfmYqAbmdbVmZ7o6qim46EcGld'
        'V2BznqmknZCIc2xfWVtrmKamoJOLd25hW1hlkaOoopWOenFkXVdfiZ6ppJiRfnRmYFZbgZeqppqTgXdoYlZYeZCqqJyWhXtqZFhW'
        'cYioqp6YiX5sZllWaYClqqCajIJvaFxWY3ehqqOcj4Zyal5YXm+cqKWekol1bWBaWmiVpaehlIx4b2JcV2KOoKmjlo98cmVeVl2G'
        'm6qlmZJ/dWdhVll9lKqnm5WDeWljV1d1jKmpnZeHfGtlWFZthKeqn5mKgG1nWlZmfKSqoZuNhHBpXVdgdJ+ppJ2Qh3NrX1lcbJmn'
        'pp+Ti3ZuYVtZZZKjqKKVjnpxZF1XYIqeqaSXkX10Zl9WW4KYqqaak4F3aGJWWHmRqqicloV6amRXVnGJqKmemIh+bGZZVmqApqqg'
        'moyCb2hbVmN4oqqinI+FcWpeWF5wnKilnpGJdG1gWlpplqWnoJSMeG9iXFhijqGpo5aPe3JkXlZdhpuqpZiSf3VnYFZafpWqp5qU'
        'g3hpY1dYdo2pqJyWhnxrZVlXboWmqZ6YioBuaFxYaH2iqJ+ZjINxa19aY3WdpqCaj4Z0bWJdYG+WoqGbkIl3cGZgX2qPnqGckYt7'
        'c2lkX2aImKCcko1+dmxnYGWCkp+cko6BeW9qY2R8jJ2bko6DfHFtZmV3hpmako6Ff3RwaWd0gZaYko6GgXdzbWpxfJGVkY6Hgnl2'
        'cG1xeY2SkI2HhHt4c3Bxd4mOj4yHhH16dXNydoWLjYuHhX58eHZ0doKIi4qGhYB9enh2d4CFiYmGhIF+e3p4eH6Ch4eFhIF/fXx6'
        'en6BhYWEg4GAfn18fH2Ag4SDgoGAf359fX5/goOCgoGAf39+fn5/gYGBgYGAgH9/f39/gIGBgYCAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAfnx3dHZ+kpeVkoqCcmtcV2J3oaqjnI+FcWpdWF9xnqmknpGIc2xfWVxsmaemn5KKdW1hWlpolaWn'
        'oZSMeG9iW1hkkKKoopWOenFkXVdgi5+ppJeQfHNlX1ZdhZuqpZiSf3VmYFZagJaqp5qTgXdoYlZYepKqqJuVhHlpY1dXdYypqZ2X'
        'hnxrZVhWb4eoqp6YiX5sZllWa4GmqqCZi4FuZ1tWZnykqqGbjYNwaVxXYnahqaOcj4Zxal5YX3GdqKSekYhzbF9ZXGyZp6afkop2'
        'bWFaWWeVpaehlIx4b2JcWGOQoqiilo56cWRdV2CKnqmkl5B9c2VfVl2FmqqlmJJ/dWZgVlp/lqqnmpSCd2hiVlh6kaqom5WEeWlj'
        'V1d0jKmpnZeGfGtlWFZvh6iqnpiJfmxmWVZqgaaqoJmLgW5nW1Zme6SqoZuNg3BpXFdidqGpo5yPhnJqXlhecZ2opJ6RiHRsX1lc'
        'bJmnpp+TinZtYVpZZ5Skp6GUjHhvYlxYY4+iqKKWjnpxZF1XX4qeqaSXkH1zZV9WXISaqqWZkn91Z2BWWn+WqqealIJ3aGJWWHmR'
        'qqiblYR6aWNXV3SMqamdl4d8a2VYVm+GqKqemIl+bGZZVmqBpqqgmouBbmhbVmV7o6qhm42DcGlcV2J2oKmjnI+GcmpeWF5wnaik'
        'npGIdGxfWVtrmaemn5OKdm5hWllnlKSnoZSNeG9iXFhjj6GoopaPe3FkXVdfip6ppJeQfXNlX1ZchJqqpZmSf3VnYFZaf5Wqp5qU'
        'gndoYlZYeZGqqJuVhHppY1dXdIupqZ2Xh3xrZVhWboaoqp6YiX9tZllWaoCmqqCai4FuaFtWZXujqqGbjYRwaVxXYXWgqaOcj4Zy'
        'a15YXnCcqKWekYh0bF9ZW2uYpqafk4t2bmFaWWeUpKehlI14b2JcV2KPoaijlo97cWRdVl+Jnqmkl5F9c2VfVlyEmqqmmZKAdWdh'
        'Vlp+laqnmpSCeGhiVlh5kKqonJWFempjV1dzi6mpnZeHfGtlWFZuhaiqnpiJf21mWlZpgKaqoJqLgW5oW1ZleqOqopuNhHBpXFdh'
        'daCpo52PhnJrXlhecJyopZ6RiXRsYFlba5impqCTi3ZuYVpZZpOkp6GVjXhwY1xXYo6hqaOWj3txZF5WX4mdqaSXkX1zZV9WXIOZ'
        'qqaZkoB2Z2FWWn6VqqealIJ4aGJWWHiQqqicloV6amRXV3OLqamdl4d9a2VYVm6Fp6qfmIl/bWZaVml/paqgmoyBbmhbVmV6o6qi'
        'm46EcGldV2F0oKmjnZCGcmteWF5vnKilnpGJdGxgWVtqmKamoJOLdm5hW1lmk6SooZWNeXBjXFdijqGpo5aPe3JkXlZeiJ2ppJiR'
        'fXRmX1Zcg5mqppmTgHZnYVZZfZSqp5qUgnhoYlZYeI+qqJyWhXpqZFdXcoqpqZ2Xh31rZVhWbYWnqp+Zin9tZ1pWaX+lqqCajIJv'
        'aFtWZHqjqqKbjoRwaV1XYXSfqaOdkIdya15YXW+cqKWekYl0bGBZW2qXpqagk4t2bmFbWWaTpKihlY15cGNcV2KNoKmjlo97cmRe'
        'Vl6InaqkmJF+dGZfVlyDmaqmmZOAdmdhVlp9lKmnmpSDeGljWFl4j6inm5WFe2tlWVhziaennJaHfW1nW1lvhKSmnJaJf29pXlpr'
        'f6GlnJeKgnFrYVxoep2jnJeLhHNuY19mdpmhnJeMhXZwZmJmc5Sem5aNh3hyaWVmcJCampaNiHp0bGhmb4yWmZWNiHx2b2toboiT'
        'l5SNiX14cW5qboSPlZOMiX96c3Bsb4GLk5GLiIB8dXNvcH+IkY+KiIF9d3Vxcn2Fjo6Jh4J+eXd0dHyDi4yIhoJ/e3l2dXuBiYqH'
        'hoKAfHt4eHuAh4iGhYKAfXx6enx/hYaFhIKBfn18e3x/g4SEg4GBf359fX1/goOCgoGBf39+fn5/gYKBgYGAgH9/f39/gIGBgYCA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgH97'
        'eoCHkJCNi4F6bmhcW3eOqamcloZ8a2VYVm6Fp6qfmYqAbmdaVmZ7o6qim46EcWpdV19ynaiknpGIdGxgWVpplqWnoJSMeG9iXFdi'
        'jaCpo5eQfHNlX1ZchJqqppmTgHZnYVZYepGqqJyVhXpqZFhWcYioqp6YiX5tZlpWaH+lqqGajYNwaVxXYXWgqaOdkIdza19ZXGyZ'
        'p6afk4t3bmJbWGSRoqiilo97cWReVl6HnKqlmJJ/dWdgVlp+lKqnm5WDeWljV1d0jKmpnZeHfWxlWVZrgqaqoJqLgW5oW1ZkeKKq'
        'opyPhnJqXlheb5uopZ+SinVtYVpZZ5Skp6GVjXlwY11XYIueqaSXkX10Zl9WW4GXqqaalIJ3aGJWWHePqqmcloZ7a2VYVm6Fp6qf'
        'mYqAbWdaVmZ8pKqhm46EcGldV2BynqmknpGIdGxgWVtql6anoJSMeG9iXFdijqGpo5aPfHJlXlZdhJqqppmTgHZnYVZZe5KqqJuV'
        'hHpqZFdWcYmoqZ6YiX5sZllWaX+lqqGajINvaVxXYnagqaOdkIdza19YXG2Zp6afk4t2bmFbWGWRo6iilo56cWRdVl6InaqlmJJ/'
        'dWZgVlp+laqnmpSDeGljV1d1jKmpnZeHfWtlWVZsg6aqoJmLgW5oW1ZkeaKqopyPhXFqXlhecJyopZ6SiXVtYFpaZ5Skp6GVjXlw'
        'Y11XYIufqaSXkH1zZl9WW4KYqqaak4F3aGJWWHiPqqicloZ7amRYVm+GqKqfmYp/bWdaVmd8pKqhm42EcGldV2BznqmknZGIdGxf'
        'WVtql6anoJSMd29iXFhjj6Gpo5aPfHJlXlZdhZuqpZmSgHZnYVZZe5OqqJuVhHpqZFdXcompqZ6YiH5sZllWaYClqqCajIJvaFxX'
        'YnagqaOdkIZya19YXG2ap6afk4p2bmFbWWWSo6iilY56cWRdVl+JnaqlmJF+dGZgVlp/laqnmpSDeGljV1d1jampnZeHfGtlWVZs'
        'g6eqn5mLgW5oW1ZleqKqopyOhXFqXlhecJyopZ6SiXVtYFpaaJWlp6GUjXlwY1xXYYyfqaSXkH1zZV9WXIKYqqaZk4F3aGJWWHmQ'
        'qqicloV7amRYVm+HqKqemIl/bWdaVmd9pKqhm42DcGldV2Bzn6mknZGIc2xfWVtrmKamoJOMd29iW1hjj6Goo5aPe3JkXlZdhpuq'
        'pZmSgHVnYVZZfJOqqJuVhHlpY1dXc4qpqZ6XiH5sZllWaoCmqqCajIJvaFxXY3ehqaOcj4Zya15YXW6ap6afkop2bmFaWWaSo6ii'
        'lY56cWRdV1+JnamkmJF+dGZgVlqAlqqnmpSCeGliV1d2jampnZeHfGtlWFZthKeqn5mLgG5nW1ZleqOqopyOhXFqXVhfcZ2opZ6R'
        'iXRtYFpaaJWlp6GUjXhwY1xXYYygqaOXkH1zZV9WXIOZqqaZk4F3aGJWWHmRqqicloV7amRYVnCHqKqemIl/bWdaVmh+pKqhm42D'
        'cGlcV2F0n6mknZCHc2xfWVtrmKamoJOLd25iW1hkkKKoopaPe3JkXlZehpuqpZiSf3VnYVZZfZSqp5uVhHlpY1dXc4upqZ2XiH1s'
        'ZllWaoGmqqCajIJvaFtWY3ehqqOcj4Zya15YXW6bp6Wfkop2bWFaWWaTo6ihlY56cGRdV2CKnqmkl5F+dGZgV1uAlqmmmZOCeGlj'
        'WFl3jainm5WGfGxmW1lvhKSnnZeJgG9qXlpoe5+lnpiMhHNtYl1kdJmin5mOh3ZwZmBhbZKen5qQinpzaWRhaYqYn5qRjH12bGhi'
        'ZoOSnZqRjYB5cGtkZnyLm5qSjoN8cm9nZ3eFmJiRjoV/dXJraXN/k5aRjoaBeHRubHF7j5OQjYeDendyb3F4ipCPjYiEfHl1cnJ2'
        'hoyOjIeFfnt3dXN2goiMi4eFgH15eHV2f4WKiYaFgX57end4foKIiIWEgX99fHp5fYCGhoSEgoB+fXx7fX+EhISDgYF/fn19fX+C'
        'g4OCgYF/f35+fn+BgoKBgYCAf39/f3+AgYGBgICAgICAf4CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgH58fYaLjo2Kh3x1a2RcYYebqqaZk4F3aGJXV3SLqamemIl/bWdbVmR4oamjnZCIdGxgWllnk6OoopaPfHJl'
        'X1ZbgJaqp5uVhHpqZFhWboWnqqCajIJvaV1XX3KdqKWfkop2bmJbWGKNoKmkmJF+dWdhVll6kaqonJaHfWxmWVZofqSqopuOhXJr'
        'XlhcbJimp6CUjXlwZF1WXoabqqaZk4F3aGJXV3SLqamemIp/bmdbVmN4oamjnZCIdGxgWllnkqOoopaPfHJlX1ZbgJaqp5uVhHpq'
        'ZFhWboSnqqCajIJwaV1XX3GcqKWfkop2bmJbV2KMn6mkmJF/dWdhVll6kKqpnJeHfWxmWVZofqSqopuOhXJrXlhcbJimp6CUjXlw'
        'ZF1WXoabqqaZk4J3aGJXV3OKqKqemIqAbmdbVmN3oamjnZGIdGxgWllmkqOoopaPfHNlX1ZbgJaqp5uVhHpqZFhWbYSnqqCajINw'
        'aV1XX3GcqKWfk4t3bmJcV2KMn6mkmJF/dWdhVlh5kKqpnZeHfWxmWVZofaSqopuPhXJrX1hca5emp6GUjXlwZF1WXoabqqaZk4J4'
        'aWNXV3OKqKqemIqAbmdbVmN3oKmknZGIdGxgWllmkqOoopaPfHNlX1Zbf5Wqp5uVhHpqZFhWbYSmqqCajINwaV1XX3GcqKWfk4t3'
        'bmJcV2KMn6mkmJF/dWdhVlh5kKqpnZeHfWxmWVZofaSqopyPhXJrX1hca5emp6GVjXlwZF1WXoaaqqaZk4J4aWNXV3OKqKqemIqA'
        'bmhbVmN3oKmknZGIdG1gWllmkqOoopaPfHNlX1Zbf5Wqp5uVhXpqZFhWbYOmqqCajINwaV1XX3GcqKWfk4t3b2JcV2GMn6mkmJF/'
        'dWdhVlh5j6mpnZeHfWxmWlZnfaSqopyPhnJrX1lba5elp6GVjXpxZF5WXYWaqqaak4J4aWNXV3KJqKqemIqAbmhbVmN2oKmknZGI'
        'dG1gWllmkaKoo5aPfHNlX1Zaf5Wqp5uVhXpqZFhWbYOmqqCajYNwaV1XX3CcqKWfk4t3b2JcV2GLn6mkmJJ/dWdhVlh4j6mpnZeI'
        'fWxmWlZnfKOqopyPhnJrX1lba5elp6GVjXpxZF5WXYWaqqaak4J4aWNXV3KJqKqfmYqAbmhbVmJ2oKmknZGIdW1hWlllkaKoo5aQ'
        'fHNmX1ZafpWqqJuVhXtqZVhWbIOmqqCajYNwaV1XXnCbqKafk4t3b2JcV2GLnqmkmJJ/dWdhVlh4j6mpnZeIfWxmWlZnfKOqopyP'
        'hnJrX1lbapalp6GVjXpxZF5WXYWaqqaalIJ4aWNXV3KJqKqfmYqAbmhbVmJ2oKmknZGJdW1hWlllkaKoo5aQfXNmX1ZafpSqqJuV'
        'hXtrZVhWbIKmqqCajYNwaV1XXnCbp6afk4t3b2JcV2GLnqmlmJJ/dmdhVlh4j6mpnZeIfmxmWlZnfKOqopyPhnJrX1lbapalp6GV'
        'jnpxZF5WXYSZqqaalIJ4aWNXV3KIqKqfmYqAbmhbV2J1n6mknpGJdW1hWlllkKKpo5eQfXNmYFZafpSqqJuVhXtrZVhWbIKmqqCa'
        'jYNwaV1YXm+bp6afk4t3b2JcV2GKnqqlmJKAdmdhVlh3jqmpnZeIfmxmWlZmfKOqopyPhnJrX1lbapalp6GVjnpxZF5WXYSZqqaa'
        'lIJ4aWNXV3GIqKqfmYuBbmhcV2J1n6mknpGJdW1hWlllkKKpo5eQfXNmYFZafZSqqJuWhXtrZVhWa4KmqqGajYNwal1YXm+bp6af'
        'k4t3b2NcV2CKnqqlmJKAdmdhVlh3jqmpnZeIfmxmWlZme6OqopyPhnNrX1lbapWkp6GVjnpxZV9XXoSYqaWZk4N5amRZWHKHpqid'
        'l4qBcGpeWmR2nKWhm5CIdm9kX11ojp6kn5SOfXVqZVxgfpCjoZeShHxvamBeb4GeoZqVioN0b2ZiZnOUnZyXjoh6dGtnY2qHlJyZ'
        'kIyAeXBsZWZ6iZqZko6Ff3VxamhxfZSXk5CIg3l1b2xtdIuSk5CKh315c3BtcIGLkpGLiIF9d3RwcHqDj5CLiYSAenh0cnZ8io2L'
        'iYWDfXt3dXV4hImLiYaEf316eXd3f4SJiIWEgX98e3l5fICGh4WEgoF+fXt7fH6DhYSEgoF/fn19fH2BgoODgoGAf35+fn5/gYKC'
        'gYGAgH9/f39/gIGBgYGAgICAf39/gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAhYeIiIWCeHRrZmRvk6GoopaPfXNmYFZZeY+pqZ6YioBuaFxXYHKcqKaglIx5cGReVlyBl6qnm5aGfGxmWlZmeqKpo52R'
        'iXVuYltXYYqdqqWZk4J4aWRYVm2Dpqqhm46FcmtfWVpnkqKpo5eRfnVnYVZYdYuoqp+Zi4JvaV1XXm6ZpqehlY57cmVfVlp9k6qo'
        'nJeIfm1nW1Zjdp+ppZ6SindvY1xXX4aaqqaalIR6amVYVmp/pKqinJCHdGxgWlhkjqCppJiSgHZoYldXcYinqqCajYNxal5YXGuW'
        'paiilo98c2ZgVll5kKmpnZiJf25oXFdgc52opp+TjHlwZF5WXYKXqqeblYZ8a2ZZVmZ7oqqjnZGJdW1hW1dhi56qpZmTgnhpY1hW'
        'boSmqqGbjoVya19ZWmiTo6ijl5B+dGdhVlh2jKmpnpmLgW9pXVdeb5qnp6CVjXpxZV9WW36Uqqiclod9bGZaVmR3oKmknpKKd29i'
        'XFdfh5uqppqUhHpqZFhWaoCkqqKcj4dzbGBaWWWPoamkmJKAdmhiV1dyiKiqoJqMg3BqXlhcbJelp6GWj3xzZmBWWXqRqamdl4l/'
        'bmdbV2F0nailn5OMeHBjXVZdg5iqp5uVhXtrZVlWZ3yiqqOdkYh1bWFbWGKLnqqlmZOBeGljV1ZuhaaqoZuOhXJrX1laaJOjqKOX'
        'kH50Z2FWWHeNqamemIqBb2hcV19wmqemoJSNenFkXlZbf5WqqJyWh31sZlpWZHigqaSekop2bmJcV2CInKqmmpSDeWpkWFZrgaWq'
        'opyPhnNsYFpZZZChqaSYkX92aGJXV3OJqKqfmYyCcGldWF1sl6WnoZWOfHJlX1Zae5GqqZ2XiH9tZ1tWYnSeqKWfk4t4b2NdVl2E'
        'maqnm5WFe2tlWVZofaOqo52QiHRtYVtYY4yfqaWZkoF3aWNXVm+Fp6qgmo2EcWpfWVtplKSoopaQfXRmYVZYd46pqZ6YioBuaFxX'
        'X3Gbp6aglI15cWReVlyAlqqonJaGfWxmWlZleaGppJ6SiXZuYlxXYImcqqaalIN5amRYVmyCpaqhm4+Gc2tgWVlmkaKpo5eRf3Vn'
        'YldXdIqoqp+ZjIJwaV1YXW2YpqehlY57cmVfVlp8kqqonZeIfm1nW1ZidZ6ppZ+Ti3dvY11WXoWZqqeblYR6a2VZVml+o6qinJCH'
        'dG1hWlhjjZ+ppJiSgXdoY1dXcIanqqCajYRxal5YW2qVpKiilo99c2ZgVll4j6mpnpiKgG5oXFdgcpyopqCUjHlwZF5WXIGWqqib'
        'loZ8bGZaVmZ6oamknZGJdm5iW1dhip2qpZmTgnhpZFhWbYOmqqGbjoVya19ZWmeSoqmjl5F/dWdhVlh1i6iqn5mLgm9pXVdebpmm'
        'p6GVjntyZV9WWn2Tqqicl4h+bWdbVmN2n6mlnpKLd29jXVdehpqqppqUhHpqZVlWaX+kqqKckId0bGBaWGSOoKmkmJKAdmhiV1dx'
        'h6eqoJqNg3FqXlhca5alqKKWj3xzZmBWWXmQqamdmImAbmhcV2BynKimn5SMeXBkXlZcgpeqp5uVhnxrZllWZnuiqqOdkYl1bWJb'
        'V2GKnqqlmZOCeGljWFZtg6aqoZuOhXJrX1laaJKjqKOXkH51Z2FWWHaMqaqfmYuBb2ldV15vmqenoJWNenFlX1ZbfpSqqJyWh31s'
        'Z1pWY3egqaSekop3b2NcV1+Hm6qmmpSEempkWFZqgKSqopyPh3NsYFpZZY+hqaSYkoB2aGJXV3KIqKqgmoyDcGpeWFxsl6WnopaP'
        'fHNmYFZZepCpqZ2XiX9uaFtXYXOdqKWfk4x4cGRdVl2DmKqnm5WFe2tlWVZnfKKqo52RiHVtYVtYYoueqqWZk4J4aWNXVm6Epqqh'
        'm46FcmtfWVpok6Ooo5eQfnRnYVZYdo2pqZ6YioFvaFxXX3Cap6aglI16cWVeVlt/laqonJaHfWxmWlZkeKCppJ6SinZuYlxXX4ib'
        'qqaalIN5amRYVmuBpaqinI+Gc2xgWlllkKGppJiRf3ZoYldXc4moqp+ZjINwal5YXWyXpaehlY58c2ZgV1p7kamonJeIf25oXFhj'
        'dZynpJ2Si3hwZV9ZX4OXp6SZk4V7bWddWmp9n6WfmY6Hdm9lYF1nipqjn5WQgXltaF9ecoSfopqVi4N1b2ZiY2+Pm56akYx+d25p'
        'YmR6ipyclZGHgHRwaGVrdpGZmJSMiHx3b2xnaoCMmJeQjIR+dXJsanJ8kZWSj4mFe3dyb21xhI2TkYuIgX13dHBveIGOkI2KhYJ7'
        'eXVzc3eFi42Lh4WAfXl3dHR9g4uLiIaDgXx7eHd4fIWIiIeEg399e3p4eX+Dh4eEg4GAfX17enx/hIWEhIKBf359fXx9gIKDg4KC'
        'gIB/fn59f4CCgoKBgYCAf39/f3+AgYGBgYCAgICAf3+AgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgH9/gYWF'
        'hYWCgHx5dXJzeImPkI6Jhn97dnRwcXyEj4+LiYSBe3h0cnN4h4yNi4eFgH14d3N0fIKLjImHhIF8end2dnmEiIqJhoSAfnt5d3d8'
        'gYiJh4WDgX18enl5e4KFh4aEg4B/fXx6en2AhYWEg4KBf359fHx9gYOEg4KBgIB/fn5+f4CCgoGBgYCAgH9/f4CAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICBgICAgICAgICAgICAgICAgICAgICAgIGAgICAf4CAgYCAgICAgIB/f4CAgICBgICAgICAf4CAgICAgH+BgIB/gYB/gIGA'
        'gICAgYGAf4CBgICAgICAgYCAgICAgICAgIB/gIB/gIGAgYB/gIB/gYCAgICAgYCBgH+AgX+BgYB/gICAf4GBgICBf4GBgIB/f4CB'
        'f4B/f3+BgYCAgH+Bf4GAf3+AgYF/gYB/gIGAgIB/gX+Af39/gIKBgIF/gYF/gX9/f3+BgIGBf4B/f4GAgIGBgIB+f4B/gIF/gX+A'
        'gX+Bf4CBf4CAf4CAf3+AgH+BgIGAgX+BgX9/gYCBf3+Bf4CBf4GBfn9/f4KBgYB/f4GBgIF+gIB/gYF/gYB/f3+Cf4KAgH9/gIB/'
        'gYF/gYCCgIB/f4F/gYGAgoCAgICBf4KBgH6Cf4CBfoF/gIB/f4B/f4N/gX+AgoB+gn9+f3+BgYF+f39/g4KBf4GCfn6CfoGCgIKA'
        'f3+CgX6BgICBfn6AgYB/gYCCf39/foGCfYGBf4B+gX99f4J/gX6Cgn1+g4CBgoCCgH5+gH9/goKAfoB+gIJ/f3+BgX+Bf4CCgH99'
        'gH+Af3+CgYJ/gYCAfoGAgH6BgYCCgYF/foCCgn6AgIGAgX98foCBf4CEgYF9f4OBfYGCfoJ9goJ/f4F+g36Bfn9+gH+Bg4J+gX5/'
        'gn6DgoCDgHt+g39+g32Bf31+gYKEf4J/g3x9f4KCgn2CgoB+g4GAf4GAgH19gISBgnyAfX1/gYKDfH1/foSDfoGCgH9/hIN9f4OB'
        'gX1+fX+Egn1+gYGAgoB+gYCDgnx9f4GDfoB/f4SCfYOBe4GCfoF+fYKDfIB/g3yFf4GCfoF+goODe399f35/foOEgoCCgH5/foSD'
        'f32AfIN9goJ9goKAgX58hYN6fYF9gYSFfoF+hHyEgYGAgX+BeoN9foODgH6DfX2Efn+AgIKCg3mBhIF/fn6Ef3uDfnyDhXt+foJ/'
        'gIKFgYGEfYJ6hH+BgYN+en1+gH2Ahn2AhX6Ce36Hfn6BgX2CgnyFg3qDgnqAgoN7hHqCfXyBh39+fXx+foeFgHuHgnt8hHyCfX+E'
        'hX6Df4N9gXqDe319hIiEfn2GfX58fXyEgYJ8h4J6goB/e4iFe4N+f4CEfYF/hX2AgoR7f4J5gYOBgX15hIWEfoKAgX16hnmGgYKD'
        'enmAg4aCeIGEen6FhX9+f36Bg4R4goV/e4J5gYF8hIJ5foF7gId+f4R+g4d8eIGBhn17fn+Kgnx9hYN/fHqAfn2BhIKEh4R/gHmB'
        'hoJ5hHiBgIN9hHx4fYaDgnl/eot+hod9fXuGfH+EgneGgoZ8g3qFfYGGdYZ7g32ChIB8hYR+d3yBfYGFe36BfHqDhH2KhYF5e3uE'
        'h4F4gX99inqFgoGFg318hnWIh3mFdXuEh4V1fXiEg395f4V6hnt8iIN8fHqBhoaKh32Fd3Z6g4OCfH2GgXqGeHyLg4SCd357fIuB'
        'fIaGhnyIhIODeHx0d4t/fYN4g4CHeXyFh317fnmAgYd8hn2Kgn+IdYF/hXiHeXaCgHp+h4eBiH98fHeDiHx6fouKh4J6dnl6fXp8'
        'jX+FgYaHgoR+hoR5eoeDdnqBhXmJfYaDhHKIg3N2jH6CgIeDfXuDeYJ0e42ChYhzfX2Ednp6jnt5jnd+iIaGiXWDd4Z+f359iHaE'
        'enx9hX+Le42Bg3uCiYR6fYR+eoOCf3iAc4aMf4RygXWHg4iBh3h3doyKeYqEg4ZveXqHiHuFgIB9hXl7iYiAcX98h4uBhH1/hntz'
        'e4J5gXmAiYZ+i4F8hnt9fYOIcIl+fIZxfHuDeH98j3qKfoSNcXV6en+Ef5KGioJ8i2+DcoaEfImEgnSJc4R8eY6GcIuLhXN4eY2E'
        'fX+Fcn+FeX18epF3eXp+fI56foqLeIh4eX+KhYmGgYhtg4ODc4CHdoeDeHSBeH97hXl9loJ3gn6Cd5SAe4aEhId7eYGNeXCLcXh4'
        'kXuPgn5/jYV1h3SHeXiOhX9yeYt8iXmCdoB/hX2Lf4R7dY1+inqHc3+AjH16g4CIcYB0hIiFgIN5iIGDeIZ/gHyCim11dZGHgnpz'
        'fnZ4mH+Hc3yJeoZ3fHmIhXaJkIWQhX+JaYlvfIB3gXx6lHOVhHiDhXB5jIiGenyJdnWRcYSJh3SKhIeKeGyNenJ/hYtxco+NeHuP'
        'c4iHgYSEhHh2g3xxiIOCiH97coKKgn96eoJ2e4h2e5hzio2JcoJ9dYF+hnN1gIqOjYpwgoGEgnaDjoVrdZOHgnp5gm2Rj3qAd32C'
        'j3d3fH52h35/j3dxh310e5KCdoyTfnqHe49xfouKb4Fsd5OSd22OkX+Ia3R+g4aDh3uGgICOaYp2cJJ+dJR0bY6PdISJjHlwiXmO'
        'eHeMiICMaHOUcH54h4NxgopyhZKEf3R/jZCHbI5sgXSKkoZqi2mMjnNzbnuCjYF8joh0fZKQbHR3d4OYgJF3fY6GaYqMf2+Ri2l2'
        'k4d9b4t9dHCTinNzcHKHgpx8hHmWbHaUin6LiHyBcIqCiHuIh2lxf5GAaXCMfX91j4N0foaPlYJpdJGCjoV5dYJ3fYaAhn94lXZx'
        'kYyKa3SHg4J/iHaKZ3WXk3aObolqbXGaj3R4cH58km51kY10j5CGh4iGbWmOgnGGiIR8gpSCj36DgXNmlHyIcICTe4+LbXhwj2hx'
        'g3dulYCYg3Jsk26MjXR6e5KLjICQdouEeX1/jWdlgHBvdYeAho9ud3+hd4mMcIGVlG2FjY+LhIWDX36MaYOHZ4Rqe5CPlnGFiX5l'
        'kmSXhHmJd3x9bYOUb32FiXB+d456l2l7j41odJ50gHyTZ4R/jYJ+dXtylIVyi4Z0nmeQd22VjGpyoHWNkoNhg2t4mImBlnF4gIiO'
        'km1qa4SLb3J2n4R6kYl/kJOFjlyJkYOLbHaGgW9zlZByinSIbWKKgnOVk5GJcWKEinmRYpWQbWqEg2aVg36ScYdyfIKAcYx4h5tn'
        'bXh4g551c4KGiJSSboKUgJOAjH9oYXlmbpaKfnuTaWyTboyRbJV3dpR1a3aKmaCGe2OTmn6PW3Zzj35pcICXm2p2m4JknXeHaZpu'
        'cZeIjnWZh4JhdpCPcIBwgZx9inVvg2yIZpx+coWOZ5eBjnZvdXB1gXqPk4SCgH6WYZqEj3ZzZKRpmH6FhoWKg22DdWt1jGeVh3CA'
        'mHF+cXGUbaaNmZKOZXB3epqNWYaPgGmCbYSEjGSUgISHeHRmlIlwfJecj151f4SJYnhwfoiXh4Zsko18i2iKjmJ8oWJrfn+hn22K'
        'Z3RymKNobm2ooGOQl2OCY5+JdmFnpH2bmHF7joBof26PcISWgnyIb4BlpW6fjVxrk5p+gHx8fHWTXnudaWqKo2eIbKZhbnGnb25u'
        'gnObk3J6km56cZyJoI9nkml9m5x7j1pjbKOcl2KPXnxsjpR2mImTh1R9l45ahGSDoml6ln94kXt1a2qDaX+fZ4OjY5yYfYSPfZRe'
        'YpJiaH14qHp2cKCKfKKJX31rcIakgnukmHaDXHdmaXh8raFlnWJ1jY+VmWBfnF2ig5OJiZVaX5V8inRncYiZaXVrbZucoHZ+dYJs'
        'cqGTllaPmItbgI9ueYiKW22Ap52aaIqFeY+VcYlUk2WJel6NcHZmbZCHg6F9hpR1h3CNdIehi4d5lXiWkHyBcnpeYZ1+YaJ2eo9u'
        'g4+LkVeXeXqYgGqPhYqIWZSRjGWRTZyKfXVuhpR5hpNqk1uKlGCRXaKDhHd2h2egfYZffKN+m12aUKCYcl+HdF2nhXt/bZKZkHdt'
        'bXlkl2l3lXhzj352jWeIcXZ7foKBi513pnaedlx0i6BfnIFtYnisooWPc1t/f413pFyMgVppq2uUdIBtrHpbq4iillKUU3Rzk3uT'
        'boqZjV6Dc6d1gmmDZZ2TnGtbaquIjFN7Z4CGd6Oeg3Fyb6ddnXh4coOSonOOlIlSkI5xhVt0haBojWJ5YX6IkH6SpXV+lVmDopR0'
        'Y3yTmYp+cGGaYoOXkXxXlKB7U2GrW6hhlJSVclV8Wa2RVpmcXW2FqpGElZBLcGFxrYKgdIRvnoNjdXdjcpt7p156lIx8lWBkcIWF'
        'jIOLoV+Jl1ehW5Vyn4RTcJ1sbappgHljhrGafG6TmXJooWVkm3V5brGUh1Knh5iVb4lLVXF/p2aqa52KiV5eYWSwn1dqbKKQpKRq'
        'WXJgdn2Xg5qBg2ORp5iFdZWWk1eWc3V5bWycjWCoj5BZflyqhXyLcVBqabeMh5p3ZpNbjm9meGV/jWuqh4ycqGehUFamh4dhaoWH'
        'eJSDWoKSb5xmqGCBbHC9mKFzdImDZYyNT5CFZXSujpGCWZCEhFpnlKZub6Fkb2J6l4x5eqphfn5pqW6ab6WYYZGijHqDS6ZxZXmG'
        'c4Rbln9ojHGZh4OSd4huVq17dKmlZFhaa4yXnF6oXJ2Dj5V/UHxmrVWVdodeeWyml7Fthmxwc2OYX3e1sqKdQl12d4qJcXtnr2qs'
        'U3x1o5xkXYuKkqxddV6Bb4WUtH5RfoyYfZR4dKejj4WUQH6GjpeWi4djQp2ZUJFaj1xcj5WvZYOpUohoqpRtlp1IcaOAi5iShYI2'
        'TIJTuZGGdJ5maJlfg3tih3uXXJacgINnZpSgj2agWaumi1aLmEdrk6p1ioWbbY14al5eYmFyuK6fhVpwmpSnUJl6oVJKV2WFgsF2'
        'YWaRj7uUS6yQZVmElZldgK98S122kKNnkJKQkICIlF4+ZVpnhZClXp2alJV9o3WZg1ODaWOkTJRjZa+LVJ6oiVdlnGuWppFpSXha'
        'loG2gIiAdYt0lKRBXHhtm7mfhG2bSE5yYrRcrF+nm22nXmhwmrGbmGZFrYVoj3ZKf52FYFqZjVl9iXN+u42hTXygk3BPap9+mY5n'
        'mqtBd2h1baurd3OIs115k5GdlJmNY0lxVaBusl+oV093kqFpg6eGV2mfXFyFe4pod8azpYt5QU2wrk6io1BVmWuItGihT5OjiEuw'
        'XHWVb42hTm+QrkeonZ1UTpGiQq54bZNTf1iol1d/WYFglXadvLNki0a4alCcqal3nUd/iGeCjlRhXG6KiK5ukLuibH16iqFeXVB/'
        'XofEopdpUZNrr4OaaFdcf320lXakXlWMW7mLUpOfZaaATW+bYXCttX+iR51lhGh7VoV4Y3N/wGt1w4FUu1Nom2p4i7CNa6BXp65n'
        'imGnWl2KrZBaWl6ecaBamYmdlHpbYnC/eFaZrkhkWGi4nWx3Ybl4o5FoaVJ3dGaZpICmkWqMYnilopx7TXNYiKhdWceJa6ZWe6eE'
        'p45sWaSdSV62dGihq4WUg4GLRJNAjl65gHVHtJVkbXKUnFZOd7t0XpG+bG1ca6ZUoleKlaGSXKdSbGu9sWdreq+bpViGYKNfnp6Y'
        'P0NpcbGBpH5NapCvhaZjU16dt5iNYZhQi1ZTp4aNTsOrd2WteENQb3hvc3uwm3e/hUS6ioyLXlZhk3WguUywQ3dxkJ15b5uNS2mw'
        'r1ZTeVeKxZBnjXmGgphZroiIQHNlmbVxaFqfrKRMpH2QlEy1PYmfVHOYmIGxhYZ2d01/SaNrW7aVZXKvdVZbb8Onlk1Mwp5Pk2qj'
        'k0l6tppEq5+MojeNS4hwrmWWeEuTSl/Nl6GZpo2AMl2skVmNrJmJfixxS1myun9hsV20YammiYYpdJJKmWh1TGDDwUhviGW5un2m'
        'eJ2NUF5Qb7eIQbN4a2iidJyYfpKcbKdIoHdWmKBPb6o9TJe+m5FgdKtbPp6dR3lapltidq1dmGGzgWimb7G0emCMY16qkWyIT3XC'
        'pYCWj2BYq2Fgl7GBnWRumHWgS2d3RsBvSHi6uV2ESbCyhJR4QEXGgZyOUnC4hEqWUmh7jqxshZVFc59/bbibSV+Lik6NiY6LaMBG'
        'YHeqb8SEqJSCV4tjWqKJsKZ7bHNBbGyRXIuxno1TppmWaV9kWFpur2+YZnG0p3BKYZervpeIkzeMba05V2xf1GKUrUqUbGGYlKW1'
        'b32RbH5kSF2pXW2+ilJaisJqi2tdi7PAioaceH97P0rDio1UlHqAiEVfwViam6CyRF12sGiUebmYX31TWHh6j3tsV5rBT6OWtI56'
        'ZHiubZpDTG6ScqKiqG1ZcndmfWyQhYaZeHByXrigTo3GYKKTj1iNQWqzk3G2g1xza7CoTJFvWWyyrkdbXXJ7YqmQY2Rsf41wbY6I'
        'qXi3fn2allFYYIeeuo55X6V1aXq2o1FMdoV+rIxzZVSwU7+wbrpmmX4+aY2cSp9on4ZKjpRQnIxyfY9lX4apXp+XqpFFXW+ziGKJ'
        'q2Stnj+tZHDBn0hlhXlagKyqcoSDRWB1wVJ8kqx1RrS/Zod+XlVcsGlgy1G1oZRIha+Zf1OAqXydNYdKbn69gFWtiV23qFmWUGtz'
        'fJiUiJtFal2zSJdbvbdxbpZtQ7hrTa+WfExvtpCcXI62j4uRVEaFiqA9kbhdd2StSomeRVKapWdzxX+Vp2avXztghb6hcLVQTKhi'
        'dWO9pFmfVE5b0lnGhXeyoUhCknWnXZB9S5Zutm9owKR+foCIc6uNS3k3o7OfPWV0vo5RYK92lJV0dDyorH9uWUi6V3aNgb5tTHay'
        'R3KmdVlmZNHHg7Y4rKiGZ0F0g5GsjYSGqltwfJ9RXXSQdH2viVW1XkpVbL2ubG24frBRRmZnqF1XjZyZkbpNtGxyWaxwh3mDUG2x'
        'gUuqasJ8kFhYr4d+j7xXcnRYeLG1mJafm09LU7ONQ3+wboSXgUtwkqaMXaN6fESxqIhNamFfa8xuULG8R4+NXrqYTK5ql1mfkI8y'
        'mpaTYWlBfF/KllS1PlWktE23WKWUb2W2i0xLe3d5oGrHqKFwU42MUEmmdb1CwEyLY2efuKM9tVCWUFyedHBkw7OgPYBSU4VjfbTL'
        's3SSZl1eoaN1ZrSEOZ6xsTJpZltmoFyEbG67cZOOyKh9pZuVlIt5PD2arpgtY4Csgjl8a5G3f2Cpd1GdknJUcrGeXldsZcOlW1OJ'
        'vaVffbZwkpCXoVahYGhUOlfKXMGGUqFhak1emWJv3U7LboFnrGqsgWmZp4lifXtkfF9xvLeLj020f0qsn5lZdGB5R75mQLRfS6Ws'
        's02zpU5iioJMwrB3S2l4erpUhn6dPrNFwo1DoEaboaxeUrRpoGhasVxnqXt+rZQ1m2uTYa+xV0Z8vYZsVpNVyVVnrIODt5Clkyla'
        'mkpLaoVbus6LQn1koY2+aGqsrzJkt6ZYp4NhdHCUPlCvloxUW8OtWLhMTWiTmImGiVO3gG9rYGSgzoJptldKcpuxoLNFfoF2q2W1'
        'oqFbKmRtlrFIR8lkuVqcnmWZfrBThziCp7ChbmeXcEOXTEmnb5mhrT98ZWxdlGlfmq+fVc+0Q06uuotCs0evr4OZkiSpkDOxl2pJ'
        'iImyXUJhhJG9cWJeiVHLRoileYSfs1CZoGdzpn1FVFXAu2FUhaepfFRzs2Zrpad1iFCsV5FLk1FVr5JcVotX0ld4uFhyl5x6dWfK'
        'gGetUE5bcciFpaOsb5aLn09IsYd7WZp9YGhmrphahbRYWrOBnVGyVLk0l4+skXlMjHldW398h75rhWeIoKNsaWi0r4B6bYxlPLCb'
        'lFpsaLxVQl2njJOCYsFqRYKOwH2RemtbhWVW07yNhk5QuKdQRXGffl9bsKi1rFmVQF9dqq5nsLCLO2Jsq4V2hISaZnWRXF2dja+Z'
        'k6JEhJN3ezp4Q667mmZupZtlcIg+b424jzpiYbelZXiFvaKgaUyYgaNXm3ZIr0dovI1ye1WueaE+rz5uVbW/pjhzlrN/lFashIaB'
        'jZuWb0ObbUNRmaU6v0OjgJNtmLA7doZ1tzeESKV4n5VVj0uIi7dMxVaufophqHFXn4WDoU54mZWtYE5oZaVqXGCsXGiggrugZole'
        'xJmqQ6qdNH5qf5hgTbBwUF+wtWtdrmiUqqeApUphSlHDipBmZ4JdWLy+U46raaNPqVaxULeHkEtrXGlWZ8KAqalFc4qmdndcpW60'
        'k1Spc6BVoW6HZKs/dWulrXG5dnWZZENXjcZgZp5/vZdDopKMSEKaUrGnnG2qcnGOVplpQq9ceZGihaCbSGeCdppgs41yfEurXKJ+'
        'TrdYaoJ1gVx4fGhu3oemUWKVx1KiULyjWJ2FiWSOmGBvYoylRapzpJSRb6VkeTm8oEtXVXFcsYldhb2Mqn9Bjq9prZCaPG1rfJZR'
        'Vl6AcpiXx1OtiqhneIOwQbBpQ4N0o5aEpXtKamGWo2mSXK2qoHtGlk9ieoqghmx2p596R3uYTbCRiE6KnF6eiXSUT6l9c2SoZY1x'
        't4OtWa9BSGLHe1Vgb36AjcqgZWxTWolfk2yWwGzEiU9dvmpRg3eXWZBdvX+imnW0Rle2V7RPpJF4n1ZvomtRhKSQpEW5qEOzXHht'
        'h5Nts4KZmoZcalVwSquZpKd0XYpVSYhkabKMYly2u1KDX1ugtbx7f2dJb2q+ZWCAtKl9lmZ5Y4prVXB0rJ6tj6OVZpZzXGeaT45m'
        't4WdXLFAUWprnL6UsZpZlUuAg5RjSqdrmFWUeId1UoyTYJt7lKFZrkhmd8BnVaNzaHmEzphJolRqeHjJi7ZDe5Z/dn9kaF1wp7B/'
        'XXKHtqCwnEtWjHudnqVyoUxXjUGYYIu1XWufdnlZX6F3oFthn5FtemCXbNCeVm+ba3V2bKxppVHJi2ePYZSUq4pbWFuDvZadmo9O'
        'd1ViVXOai4ZxwWa4aahBl2JYoIq3dH2sdUKTVW6IlI5tsqh/Y3hzY4OmnjyldmehW61KbG1ygI3AiKuHbHODhnKmlohqWWNyWGBp'
        'qpN6f5B8aY98gLVJf71RmF+MYJShjaNVkY90iHd/T3C8aHBtjlifbKu4UVKdmX+IUI+iUJ6OYbydYVSHgqV4SKCcqqWOh3aIOUdP'
        'vqamTk2CkaCkXpVShV6AfZabUoZmnW6PilhqioO7l1KIeGZ1oIqPmZNEhlnAikatrFJuUmKWg498km6FeqiHZKVvdoV2n21bpVyk'
        'gYV0bKSwaXppipJ2VXBgu6tvqUmYTY24o29LVWtijpqAgJlYZm6Mcritq6qSi15YqniZbkuKopeOi4BnZZucOH1HdX5ytHF/mFty'
        'ooOpbnWVTKhVY2qWb2Sob32It2+NtXqJWF57lbRnYWKuX2ttuK+MflF4Z3KjsJuCXKNSbaZtZ7J2S3B2boy4sJCWZHtSqHaVZY+d'
        'c42Zb2hZrlOOqVCUgnKpdHpVXIFwuZt2gXWZRn6QYJGpb4V9dGGkWqSkpoZ9WF1seKijoINYgI9lkV1/hIGghU5ulopLmoaMjH5z'
        'mE9bjJ6XlnCoeo+TYEdRtlGIonpqkYZ6ZGpzhriIfHOxZmOEk1dyuoR9q5ieeHh7Y12Lj4mlS5SBmkOYYVWLjIB/snFtd6xLdYxb'
        'sIGBi3lclayJdktwb7iKqoZ1j5tihVqWhmFnfYpssGtcbqVzk5dOiW2YXaiud2lgc2yRpKWklD9uXKycpId1RKWckWuaUoppSZGu'
        'al2mTKN9mWdmhIZndWJ5sIB5s1eGbJ+SUmeyomSUaq1SeJd0kqF9Y1x0gJddtVmJaIu2YKOlcW+diU9vhJp+VJ59YXOkqYpYaXKH'
        'h2CVXXVtrrGhWnyGkW+IaoSaaF+2Z1d1t3RljXmMplSakHeZg3uPYF2Kb2isbpxshIOZdoSkiJ5XkVJkimJ3c6eVamedpY1tfXWj'
        'p39Ti3ybn1qISnhfY7hepGZ5kah7WqOLjppJb4qnhE9zbWqtsIpkhYKgYGlyYZtgnGCatGtfd6hbtY6XcICUlVacaKR/eW92cpyh'
        'kF1mlVV9jX53nZ2GYmF8jGtZmWxwjpWYo16fd4daboxqc3J0p2xmb46kfLJ8W3CkfqR5j32UW6mcmmNqilF9a257qX+cdJdbZKKm'
        'Vmpijox/sZhVbaprnoNwdmOrZWWupZKAVox8j3SeiltWW3yPn219mnNkk2tzq2eoeZttj5mFmWKIbGl9m3ppk3Zhq6FViIBZiGeM'
        'lXt2aYSEgXl/ZG6sbJpksnqmZ3umZ5llYq2gXYKDfZ1bdoGEb3ljkXyXk2aHbWyTmZphnoSdTJSad4V0aaNMhIybnWmVSW17X4yV'
        'bYSPbYdnkpxujZ2GdV5nmoiBbZ9jdGu0i2Z1dHOSZLFspIxpXmaSiqB0pl1usHloaoSMlI5/bWGPo3Z0dGyjbo6pgIp/bWdpppKU'
        'hllgd69pZX+meHqGh4ufdYdlcW+niIGQX22gaH6EinhhY6+CcYCNfpRbf4d/m4mShGFni3ePkpyacGKYh3+WeVF0jlx3c6xrpISb'
        'TpOAj3lmeaaaVXtwfmacaGR7b46aZJaYeGlzb3eHo56Col6TaINyjmqmdV6Ioolgo2l2pX9rZ5xehaJxc2p7doB7cKeAj6tjYKaS'
        'g26gi12ZYF5nhWylf32VZY+FZZxsiaRwmmuUhJxhhGaKlo6IVoCFbJVoY5eKimqcZKhbeqSQXZdsiWh/nnxsaGyjhp1yi2FojJyR'
        'Yn6Od6aXgld6kYmSZ2+Bn46Oa4poa2J3jph1dqFtg3VzkX2Ybpp9fmqCiHOGkGeenGCZYHF0gZyeV5CDeqGGa12cYG9wgZJ7goN8'
        'jYiHZal2kIebZ1+WkpNjmIyFZYN8lHN4X49xiYpzhY5uZKN1jZRYhHiak3eai19ma3B4c62QcnqcZWWZnHaeZGCWkl55dWqYbZJv'
        'nn6XhWycdniIbo6UhpVnXZZinJ6UdXJvbmp6nHSbiXxtcGlyd46NdW2JmHClcI+WfI5pbIaWaYl7loaJapuEdZWSX2qIbYeEaJ9j'
        'c6KKiYuWjnNshJJjXmmKf4WXcJyEkW9hjpN8YWyPZ2yMdniNfJCQn3iWgl6Td4WWkIRziYmGW2R0bmydbnBzdo16rIyaYWund5yD'
        'hmOebppxlH1hhI97e42Ac26IY5Z8j35wiIB4fHOdkXOLbZxqdG6Wc5Fpo3WCcIJqiJxzem6SimuYl3yVaYqNfnGVYGt6bomGe4h8'
        'k5VtbJtwkGuMiomTfIiTXZZ/jGt7Z5l4c45xhY+Ud2ljfZN0boONdJVzdJt5gniNjnKQinhtfXx6kItqkISGgWuBiZN3fpdifY+P'
        'XnF3enB0m4lwe46CnmZ3kIKZgJV+jmmIk2WGemx8a5SVfXWAeZllnJR0YnuRcGuce32XlnJ4kXh0hYxhbJ6AdZqGfW5/jZJ2inB0'
        'fGt2moaJbo9+fn6UaICJdmp1hJGHi3yYcX5+i3uLhXZygXSGd2qSkHNwmpFweWx/fZeQb4x2c4t+hZaJhXx4fHdwk3SChHyViWdx'
        'kZV9ZIGZk3V4km6IbJSMe22SjWN+jW6TgIyFeGiJh3SQeIl2dJF8c3xrlZNsdHRwl3eYc2p0c5WGkIaGgYmFi3V8co15jnJ1l5GE'
        'enl0f3F/fGuUcpVqeXyWfIxsdZyFa391hZmKa5l1fHR8dIRyinqLi2+Nb4SFnIlzb5RviZKScYKSfXlxhYCDhXJsf42Gi4NrkWlt'
        'jJZsf5iBb3qBco2KlGx+jnh7g4mAf2pxeo+BlIWGa4R/gW2VcHiIf4ZvmHF/kn6Dd5ZzfnSRfoqLh4Z+b3N6lI2Jd2pveXWMfZGK'
        'kG2NdINuh5KIinKNan1scZKHd3mYfn2JdnSEfZNweJJ7epVxeYR/doGTiW97i4Bwjm6UcnJ6f36BknORgIaGhYOHgn9ve45zfoB/'
        'fYCRj3B3i3Ryl3SRc4yBc4R6kY1wjHBujJFwjXRxl5Bzhohyg45xhnWGgnl0eHKBmXWBeoqJj3lxh4Z5dXKCi4p8hYCSen92kIxt'
        'b3pzmYl1dod2koZ7dJWEjoZ/iG96f3qAbXuCgI5vjIaIcIGBk4F0kHZ5hXN+d4eKg410c5RyeXp+g5J7gnqGenl5d3mWgXuQjn+K'
        'hWyNeIyJaYR9iH+McIWIem6Ain13cn+Qf3+KfYxwg3SPcYGDhnR2eIeQdJGQgn5xiYWBdXp9eI2Nb3uJcouJenR5fZN2fn+KeYZ0'
        'en95mJF8dnp2e3uPfYWScomQfnlzj4VwhIZ2e3t+fJF4domPcYOHioh6fXCFf3R5iIh2hI2PioR6bH6Ihnd+eXiPiot4cXWEgniI'
        'jnKMdnR+joeHiniJcoSBinCDh3t6dY99eHyGgYR+i3WLhXiMgohufXN3h3SEkH55eZB0fIZ3gZB5h3qAhHiAiXyHfI14g3t/iXOJ'
        'jIGIdn2HgnCIeYR3fXh/hnqEh4V6d4+HhW+KgHN1e4SRiYeCc3h+fXp8gYZ+fY1+hod6doh3h4uIgYJ2dXR5eoN6kXd5jI19gnuI'
        'jH53c411g3mMf313hYZ+g4CDgHt3fIl8gXqGgYB6eoOOh3aEhXWOh4l2eniJg4R/gIZ4eXd8hH1/e32OeIV+hX5+fYl4foV5hoeB'
        'd4Z+fId+gYR+e4SGhoZ2e4OFeXx+iXmCfYaDgnuDfIh2f4h0g4B6d41/d4GMioB8eYiJd3aFhH+AhYZ/hoBygnd8fnqKiXx3eYR/'
        'eo2LgH9/hXOJdHqKgXZ+hH2DioGEgIZ7iHh6iHuFf3WJdoaBgn2JhIZzdomBdop4g3l/fH2Fh3iCenl9hIaGe4CJenh8iXqHf4WJ'
        'g3iFg359hn9/h3x5hHd/hYGIe4V/eXiDfIZ4iIKFhH2GgXp4iH55fYR4goB/e4qGeoV/eYeDgX98iHeCd4eFe4Z8fYN5fol5f36H'
        'fXqBfIt4g4h6f35/iHl+eoKIe4CKgYCCeHqKiHyAenmKgXmIeXl9f3+GgIJ8hn6GiHeHfoaFfH13fn+AgoiEgIB7fIeDe32FfXiB'
        'gIF5fYGJgHx8hYZ/fXt+gYCEe4iDh4V5hXh+hHmDhoCFfHl8fIN+hYR4hIB+e4B9fYWIgn9+hIZ7eYOAhYSEd4Z9fHmDfIOCe3t9'
        'iHuFfH1+hH+GfX6EfH2AhIOHg31+hoZ/fIGBgHuCgoKCgYR9e4SAfIN9fXt/gnp/hn+Dhnx5f4F9fYiHf4GEg3+Eg319gnmFeYCF'
        'hHqBfoSDgXt8gnyCfICChIJ7g4N8eYR6g4GGhIF4gIN9gnyCgX1+g39/fYSDfHyAhIN9fYKDe35/gH1/hn2AfYeEg36EgX58hHyA'
        'hIR/e4KEgYN/fXx6gn+EgHyEgXt8hYF8gH2HgoWAgIOBeYOEfHx/hYF9foGEfoKAfIOCe4F+fH+Ff4F9foKFf4J8gIKCfHyCgYCB'
        'gnx+foJ9gH6DfoOEf4V9fYWCfX6AhIF+goF/f4F/hH18gn2AgoGCgH2Df36BgoN9foCBfIR8hH+CgXyEfn6Bf3x9hIGAgH6Fg4CB'
        'gYCBfIN+fX59foSChIN9fn6EfoN9g3+DfIKBe36BfoF+hH5/g359gYKCgoKAgn+BgHx+gIKBfICDfYJ+f4R+foGAgoB/gYGAgIGA'
        'gYKAfH+Bfn6CfoKDgIGAfn6CfYCEfn+BfoF+gYJ+f4N+gYGDfn2Cf36Af4GCg399foKBgoCCgoF8gX+DgX1/fn9/g4N/gIF+gIGA'
        'goCAfYCCf4CCfYCBf32Df3+CfoB/gH9/gICAhIF/f4N/gX6Afn+Af4CBgX9/gn6BgICCgYF/gYCAgn5/gH+BgYF/gH6BgoF/gX6A'
        'gYJ/foCAgIF/gIB/f4OBgIGAf3+AgoJ9gH6BgH+CgYB/goCAgX+BfoF+foGCfn+CgH+AgYKAgYF/gIB9goB/gICAf4B/gYGCgH9/'
        'goCAgIF+gH+AgoCAgYCAgYCAgYCBf3+BgX9+f4J+gYCBgH9/gICBf4CBgYGBfoCAgYGBgH6Bf3+BgIF/f4CAgYCAgYCBf4B/gX9/'
        'gH+Bf4GBf3+BgYCBf3+BgICAf4CBgICAfoCBf4GBf4F/gH9/gICBgICAgH+Bf4CAgIGAf4F/gICBf4CAgIGAgH+Af4GBf4CAgIF/'
        'gH+BgIF/f4GAgIB/gYCAgICAgICAgICAgYGAgICAf4CAgIB/f4GBgICAgH+AgIGAgX9/gYCAgH+Bf4CAgH+Bf4GAgICAgICAgICA'
        'gICAgH9/f4CAgICAgIGAgIGAgICAgICAgH+Af4CAgICAgIGAgICAgICAgIGAgICAf4CAgICBgIGAgICAf4CAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAf4CAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICBg4SCgH94dXV8jJCPioB+cmVpdJCgmZSFe3FXWW2Mr6aZjnpxWE5phaismJKAcWBLYoOfsJyR'
        'iHFkT1iAma2jj413Y1VReJimqZKMgGRYUGyWoqiZiodpVlNikKOkoIyHc1VUXoSloqGShntZUF55oaWemYd+YkxcdJipnJuNfWtN'
        'VnKPqZ+YlX9vU05viaOllpiGb1tLZoebqJmVj3FfTVyFl6Sfk5N5X1JVfZefo5WTg2BUVHGXnKGbkIpnUlZokZ6dn5KLcVFVZIeg'
        'm5+YinpVUGR9nZ2bno19XktheZWhmJ6UfmdLWXeNoZuam4FrUVF0iZyfmJ2JbFhNbImVoZmbkm9bUGKHkp2emJd3WlNbgJOXoZqX'
        'glxUWnWUlZ2flopjUFttj5eYopiMbU9Za4aZlaCfjHZTUmp+l5ibpJB5W01ne4+bmKOYe2NNX3uJmpmfn4BmUld4hpSdnKKJZ1dT'
        'cYeOnJ2gk2tZVWeGjJehnph0V1dhgI6RoaCZf1lWYXeOj52lmIZgUmFwipGWp5yJalBeb4KSk6SjinFTWG98j5SeqJB1W1JseoiW'
        'mqiZdmFSZXuClJujoXxjVl15gY2doaOGY1pac4OHm6KikGdaXGqChZWloZZwWF5mfYeOpaSXe1hbZnWHi5+pmIJfV2dwg4yYq52E'
        'aFRkcHyNlKilhm5XXnJ3iZWiqo1wXVlvd4GVnqqWcmJZaXl8kZ+mn3hiXGJ3e4qgpaKCYl9gcn2DnaehjGVeYmt8gZaqopFuW2Ro'
        'd4KOqaaTd1tianGBi6OslX1hXWttfIubrpt/aFppb3WKmKujgm1dY3FxhZelqYhuYl9vcn2Xo6mSb2ZganR3kqSnmnVlY2Vzdomk'
        'pp5+ZGZkbniCoameh2ZkZ2h2f5mtn4xuYGlncX+RrKWNdmBnamt+jaarkHtlY21peIyfrpZ8bGFra3CKnKuffm9kZm5shJynpYRv'
        'aWNsbXuapaaOcGtlaG91lKeklXRqaWRtdIuopZh9aGxlaXSEpKmYhGtqamRygZytm4hxZ2xkbICUrKGJeGdraGZ9kaeoi3tsZ2tk'
        'dpChqpJ7cmZqZ26Nn6mafHRqZmlphp+loIJzb2VoanyepaCKc3FoZGt2mKifkXdwbWJpdI+poZN+bnBkZHOHpaaThHBuaWBwhJ6q'
        'lYZ2bGxgaYOYqpyGfG1rZGN/laaiiH5yaWdhd5ShpY59eGlmY26RoKSWfnpuZGVqiaGhmoN4dGRjaYCgopuKeHZoX2l5mqaaj3t1'
        'bl5md5KnnJCCdHFhYHWLpKGPh3dwZlxxiJ6lkYd9b2ldaYeZppeGgnFpYGOCl6KdiIJ3aGNgepeen42BfWpiYnGUnp6TgX9wYGJs'
        'jKCcl4Z9dmFga4OgnZaMfXlmXGp9mqGVj4F4bFpme5Ojl4+HeHBdYHmNoZyNi3xwY1t0jJugj4uCcGZbbIqXoJSJh3NmXmWGl5yZ'
        'iod6ZWBifZeamo6GgGhfY3WVm5iThoJuXGNwjp2WlYqBdV1fb4admJOQgnhjWm6BmJySkoZ5aVlpf5Kek5GMemxbYn2Om5iPkH5t'
        'YF14jZebkI+FbmJccIyUmpSNinJiX2mIlJaXjot6Yl9mgJWUl5KKgGVdZnmTlZSWi4NsWmV1jZiSlo+Dc1thdIaYlJSUhHZgXHKC'
        'lJeRlop3Zllsgo6YkpSQeWlcZYCLlpaSk35pX2B7jJGYkpOGa2FgdIuPlpaRi3BgYm2IkJKYko14X2FrgZGPl5aMfmJea3uPkZOa'
        'joFpW2l4ipOQmZOCcFtkeISSkZaYhXNgX3aCjpSTmot0ZF1wgomUk5iRdmdeaoGHkZaVlX1mYWV9iIyXlpWFaGJldomKlJmUim1f'
        'ZnGFi4+blox1XmVvf4yMmZqMe2FhcHqKjZSdj35oXW55hY+RnZV/bV1peYCNkZmag3BhY3h/iZOWnIlwZWFzgISSlpqRc2ZjbYCD'
        'jZiZlXplZWp8hIiYmpWCZmRqdoSGlJ2Vh2tia3KBh4+el4lyYGlyfIiMm5yKeGNlc3iFjJegjnpoYnF4gI2Tn5R8bWJteXyKk5ya'
        'f25laHh7hZSZnIduaGZ0fICSmpuOcWhob3x+jZyakndmamx5f4ebnJN/Z2ltdICElqCThGtmb3F8hZGhl4VyZG1yd4WNnpyHdmZq'
        'dHSBjZmgi3hrZnN1fI2WoJJ5bmdvdniJlp2YfW9qa3Z3g5ecmoNubGpyeH6UnZmKcGxsbnh8jp6ZjnZqbm11fYidnI99am1vcHyF'
        'maCQgW5qcW94hZOilIJzaXBwc4SQn5qDd2ttcnCAkJueiHdvanJxeY+Zno54cmxvc3WKmZyUe3FvbHJ0hJmcloFwcWxvdX6WnpaH'
        'cnBvbHR8kKCXinducWxxfIufmot9bnFvbXqHm5+NgHJucWt2h5agkYB2bXFtcIWTnpeBeXBucG6Ak5ubhXl0bW9ueZGam4t4dm9t'
        'b3WNm5qQe3Vya29zhpuakoF0dWxsdICYnJKGdnRwaXJ+k5+TiHpyc2lufY2fl4h/c3JsanuKm5yJgXZwb2h2ipedjoB7cW9qcIeV'
        'nJOBfHRtbGyClZmXhHx4bWxte5SZl4p7enBqbXaPm5aOfnl0aWx1iJuWj4N4d2tpdIOZmY6HenZvZnKBlJyPiH51cmdtgI+ck4eC'
        'd3JqaH2NmZiIg3txbGd3jJaZjIJ/cmxocYqVmJCCgHZram6ElZaThX97bGltfpSWk4p/fW9nbXmQmJGNgXx0Zmt3ipmSjYZ8d2hn'
        'doaXloyJfndtZHOEk5iNiYJ3cGVug4+YkIiGeXBoaX+OlZSIh35wamd6jpOVi4WCcWpodIuTk4+Fg3ZoaXCGlJKRiIN7aWhvgJOS'
        'kIyDfm1lb3yQlY6OhX5yZGx7i5aPjYl+dWZoeYeUkouMgXZqZHaGkJSMjIZ2bWVwhY2Uj4qJeW1na4KNkZKKin9taGp8jY+SjYmD'
        'cGhqdoyPkJCJhXVmanOHkY6Ri4V6Z2hzgZGPj4+FfWtlcn6NkY2QiH1wZG59iZKNj41+c2ZqfIaQkI2PgnNpZnmGjJGNj4d0a2Zz'
        'hoqQj42LeGtob4OKjZGNjH5raW1+i4uQkIuDbmdteYqMjpKMhXNlbXaGjYySj4V4Zmp2gY2Mj5KGe2pmdX+Kjo2TintuZXJ/ho6N'
        'kY99cWdtfoSMj4+RgXFpanuEiJCPkYdya2p2hYaOkZCLdmprcoKHipKQjHxqa3F+iIiRk4yBbGlxeoeJjZWNg3FmcHiDiouUkYR2'
        'Z214f4mLkZSGeGppeH6GjI+VinluaHR+goyPlI97b2lwfoGJkJKSf29rbXuChZCSkoVwbG13goONlJGJdGtudICEiZSSi3pqbnN8'
        'hIeSlYt+bGt0eYOHj5eNgHBpc3h/h4yWkYF0aXB5fIaMk5WEdmxteXuDjJGWiHdva3Z8f4uRlY55cG1yfH6HkpOQfW9vcHp+g5GU'
        'kYNwb3F2f4GOlpGHc21ydH2BipeSiHhscXR5goeUlol8bm92d4CHkZiLfnJsdXd8h46YkH91bXJ4eYWNlZSBdm9weHiBjpOVhnZy'
        'b3Z6fYyTlIt3cnFzenuIlJSOfHFycXh8g5OVjoFxcnN1fIGQl4+EdHB0c3qBi5iRhXhvdHR2gImWlYZ8cXJ2dH6IkpiJfHRwdnR6'
        'h5CXjn12cHN2d4WQlZJ/d3NxdnaAkJSThHZ1cXR3fI2Vk4l4dXNyd3qJlpOLfHN1cXV6hJWUjIB0dXNyeoKRl4yDdnN1cXeBjZiP'
        'g3pydXJ0gIuWk4R8dHN0cn2Kk5aHfXdydHJ5iZGVi315c3N0dYaRlI9/eXZxdHWBkZOQg3h4cnJ1fY+VkId5eHVwdXuLlpCJfXd3'
        'cHJ7hpWSiYB3d3JveYSSlYqCeXZ1b3aDjpaMgn11dXBygoyVkIN+eHRycH6MkpOFfntzcnB5i5GTiX58dXFydoiSkYyAfHhwcXWD'
        'kpGNg3t6cm91f5CTjYZ8enVudH2MlY2If3l3bnF8iJSQh4J6d3FueoaSk4iDfXdzbXeFj5SKg4B3c29yhI2SjoOBenNwcICNkJCF'
        'gH1zcHB7jJCPiIB/dW9xd4mRjouCf3lucHaFko+LhX57cG52gZCRiod/e3RsdH+MkouIgnt2bXF+iZKNh4V8d29ufIeQkIeGf3Zx'
        'bXiHjZGJhYJ3cW50hY2PjISEe3FvcYKNjo2Gg35yb3F9jI6NiYOAdG1xeoqPjIuEgHhtcHmFkIyKh4B7b214go6OiYmCe3JrdoGL'
        'j4mJhXt0bHKAiI+LiIh9dW5vfoiNjYiIgXVwbnqIi46Jh4R3cG52houMjIeFem9vdIOMi4yIhX5wbnN+i4uLi4WAc2xzfImMioyH'
        'gXdscXuFjYqLioF5bm56g4yLiYyDenFseIKJjYmLh3tzbHSCh4yLiol9c25xgIaKjImKgXNvcHyHiIyLiYR1b3B4hoiKjYmGeW5w'
        'doOJiI2Lhn1vb3Z/iYiLjYZ/cm11fYeKiY6JgHVsc32EiomMjIF3bnB8gomKi42DeHBueoKGi4qNh3lybnaChIqLjIp8cm9zgISH'
        'jIuLgHJwcn2FhYuNioN0b3N5hIaJjouFeG5zeIGHh46NhXtvcXh+hoeMj4Z9cW54fYSIipCJfnRudn2BiImOjX92b3J9gIaKjI6C'
        'dnFxe4CDioyOhndycXiBgoiNjYl6cXJ1f4KGjo2KfnFydXyDhIyPioJzcXV6goSJkIuDd291eX+Eh5COhHpwc3l9hIeNkIV8cnF5'
        'fIGHi5GJfHVwd3x/h4uPjH52cXV9foSLjo6BdnNze36Bi46OhXZzc3h/gImPjYh5cnR2fYCFj46JfXJ0dnuAg42QiYB0c3d5f4OK'
        'kYuBd3F3eX2DiJGNgnlydXl6goiPkIR7dHN6en+IjZGHe3ZzeHt9h4yQi3x2dHZ7fISNj41/dnV1enyAjI+Ng3Z2dXd8f4mQjYZ5'
        'dHd2e3+GkI6HfHR3d3l/hI+Qh391dXh3fYOMkomAeHR4d3qDipGMgHp0d3l4gYmPj4J7dnV5eH6JjpCFe3h1d3l7h46PiXx4dnZ5'
        'eoSOjot/d3h1eHuBjY+Lgnh4d3Z7f4uRi4R6d3h1eX+HkY2FfXZ4dnd+hY+PhX94d3h1fIWNkYd/enZ4dnmEi5CKf3x3d3d3gouP'
        'jYF8eXZ3d3+Kjo6Ee3p2dnd7iY6Nh3x6eHV3eoWPjYl/enp1dnqCjo6Jgnp6d3R6gIyQiYN8eXh0eICJkYuEfnl5dXV/h4+NhIB6'
        'eHZ0fIaNj4WAfHd3dHmFjI+IgH55dnV3g4yOi4F+e3V2doCMjYuEfXx2dHZ8io6Lhn58eXN2e4ePi4eAfHt0dHuDjoyHgnx7dnN6'
        'goyOh4R+enhyd4GJj4mDgHp4c3WAiI6Lg4F8eHVzfYeMjYWBf3h1c3qHi42HgYB5dXR3hIyLiYKAfHR0d4GMi4mEf352c3d+ioyJ'
        'hoB+eHJ2fYeNiYeCfXpydHyFjYqGhH57dXJ7g4uMhoWAe3ZxeIOJjYeEgnt3c3WBiIyKhIN9d3R0f4iKi4WDgHd0dHuHioqHgoF5'
        'c3R5hYuJiYOBfHN0eIKLiYiFgX51cnh/ioqHh4J+d3F3foeMh4eEfnlydH6Fi4mGhn96c3J8hImKhoaCenVyeoSIi4eFhHt2cneD'
        'h4mJhYV+dXN1gIeIiYaFgHZzdX2HiImIhIJ4cnV7hYmHiYWCe3J0eoKJh4iHgn10cnqAiIiHiYN+dnF4f4aJh4iGfnhxdn+EiYiH'
        'iIB5c3N+hIeJh4iCeXRze4SGiYiHhXp0c3iDhoeJh4Z9dHR3gIaGiYiGgHVzd36GhoiJhoF3cnd8hIeGioeCenJ1fIKHhomJgnxz'
        'c3uAhoeHioR9dXJ6gISIh4qHfXdyd4CDh4iIiH93dHV/goWIiImCeHR1fIOEiImIhHl0dXqChIaKiIZ8dHV5gISFiomGf3R0eX6E'
        'hIiLhoB2c3h9g4WGi4iBeXJ3fICFhoqKgnt0dXx/hIaIi4R7dXR7f4KHiIuGfHd0eYCBhoiKiH53dXd/gYSJiYmBd3V2fIGCiIqJ'
        'g3h1d3qBgoaLiYV7dHd6f4OEi4qFfnV2en2ChImMhn92dHp8gYSHjIiAeXR5fX+Eh4uKgHp1d31+goeKi4N6dnZ8foCHiYuGe3d2'
        'en5/hYqKiH13d3h+f4OKioiAd3d4fICBiYuIgnh2eXp/gYaMiYN6dXl6fYGFjIuEfXZ4e3yBhIqMhX53dnt7f4SIjYd+eXZ6fH2D'
        'iIyJf3p3eHx8goiLi4F6eHd7fX+HiouEenh4en1+hYuKhnx4eXl8foOLi4d/eHl5e36BioyHgXl4enl9gYeNiIJ7d3p5fIGGjIqC'
        'fXd5enqAhYuMg315eHt6foWJjIZ+enh6e3yEiYyIfnt5eXt7gomLiYF7enh6e3+Ii4mDe3p5eXt+hoyJhXx5enh7foSMioV/eXp5'
        'eX2CioyGgHp6enh8gYiNh4F8eXp4eoGHjImBfXl6eXmAhouLgn57eXp5fYaKi4R+fHl5eXuFiouHfnx6eHp6goqKiIB8fHh5e4CJ'
        'i4iCfHx5eHp+h4yIhH17e3d5foWMiYR/e3t4eH2Di4qEgXx7end8g4mMhYF+enp3eoKHi4eBf3t6eHiAh4qJgn98eXl4foeJioR/'
        'fnp4eHyGiomGf357d3h7g4qJhoF9fXh4e4GJioaDfX15dnp/iIuGhH98e3Z5f4WLh4OBfHt3d36EiomDgn57eXZ8hIiKhIF/e3l2'
        'eoOHioaBgHx5d3iBh4mIgoB+eXh4f4eIiISAf3l3eH2GiYeFgH97dnh8hIqHhoJ/fXd3e4KJiIWDf314dnuAh4mFhIB9enV5gIaK'
        'hoSCfXt2d3+FiYiDg396eHZ9hIeJhIOBe3h2e4SHiIaCgnx4d3mCh4eHg4J+eHd5gIeHh4SBgHl2eX6GiIaFgoB7dXh9hIiGhoOA'
        'fHZ3fYKIh4WFgH14dXyBh4iFhYJ9eXV6gYWIhYSDfnp2eICEh4eEhH96d3d+hIaHhISBend3fISGh4aDgnx3d3qDhoaHhIJ+d3d6'
        'gIaGhoWCf3h2en+FhoWGg4B6dXl+hIeFhoWAfHZ3foKHhoWGgXx3dn2ChYeFhoN8eHZ7gYSHhYWEfXl2eYGEhoaFhX95d3h/hISH'
        'hYWBeXd4fYSEhoaFgnt2eHyChYWHhYN9dnh7gIWEhoeDf3d2e3+EhYWHhH95dXp/g4WFh4V/e3Z5f4GFhYaHgXt3d36BhIaFh4N7'
        'eHd8gYOGhoaEfHh3eoGChIeGhX54eHl/g4OHh4WBeXd5fYODhYiFgnp3eXyBg4SIhoJ8dnl8gISEh4iDfnd3fH+DhIaIhH55dnt/'
        'gYSFiIZ/end6f4CEhYeHgHp4eH6AgoaGh4J7eHh9gIGFh4eEfHh5e4CBhIeHhX54eXp/gYKHiIWAeHh7fYGChomFgXp3e32AgoSJ'
        'hoF8d3p9f4KEiIiCfXh5fX6BhIaJg315eHx+gISGiIV+enh7fn+DhoiHf3p5en5/gYaHh4F6eXl9f4CFiIeDe3l6e3+AhIiHhH14'
        'ent+gIKIiIR/eXp7fYCChomFgHp5fHx/goWJhoB8eHt9fYKEiIiBfXl6fX2AhIeJgn16eXx9f4SHiIR9e3l7fn6Dh4iGfnt6en1+'
        'gYeIhoB7fX6Bg4OGiIR6bWprbXiKm6GdmIx9eXdwYVpja3OIoKmim5mQhoJ4YktKWWh+nrW1pJiQf3VwZ1hRX3J9j6SqoJOUkoZ7'
        'bltJSWB3jKW2sp2PjIFxaGBYVGJ7ipakp52PkJSGcmNVS05nhpmps6yZiYiCbl9aWVtog5aboaKaj46ShGlYUE9XcJKlqqylloeD'
        'fmpXVVxkcImeoJycmJKNjH5gTk5WY3qbraqknpSHfXdlUlNgbnuOoqKXlpeVjIJ1WklOXnGFoLGpnJiTh3dsYVFTZXiGk6KilZGY'
        'l4p3aVZIUWh+kaKvp5eUkoVwYVxUV2yCkJadn5SQmJeGbFxUTFZxi5ujqqWWkI+BalhXWl9yipeZmJuXkpaTf2NSUlReepWio6Oi'
        'l42IemNSVGFpeZCcmpSXm5WSi3VbTFJeaoKcpqKdn5qLf3FdUFRndYGTnZmRlJ2ZjH9sVktUaHeJn6ehmpybiHRnWVJYbYCJk5yY'
        'kpSem4VyYlRNWHGDj5+moZqZmIRpXFdWXnOJkJKYmJWWnJh+ZVpUU194jpWco6GblpF9YFRXXmd5jpaRk5iZmZiQdltUVltofpWa'
        'mqCjnZKGdFtQWWZxf5CYkY+ZnpuRhG9WUFplcYSYnpqepJ6NeWpYT1xue4WQmJKPmqKaiHdnVVBebnuImKCcnaSchW1gWFRgdoOK'
        'jpWVkpuiln9qYFdTYnaDjJehoZ6gln1jWFpcZXuKjY2RmJibnpB2YVpaWmd9ipCWoaagmo1zW1NcZW1/jo+MkJufmpaHbltXXmNs'
        'gY+Tl6GpoZGBa1dTX251gY+QjZGepJmLfGdYV2Jsc4OSlpqiqp+Hc2RXVWJ1foONkY+Un6SVf3FkWFllc3qEk5uepKeafWZeWVtn'
        'eoWFipKUmZ+hj3VnYltcaHmBhZSgpKWgkXRdWl1ibX2Jh4iTm56emIhuYGBgYWx8homUpamkl4VtWFhjanJ/ioqIlKGhmo5+aVxf'
        'ZWdvfYqOl6itoIx4Z1dYZ3F4gImNjJakopODdWhcX2ltc3+NlZyprJqAbGJaW2p4fIGIkJOZpKCMeG1nXl9rc3eAj52jqKeRdWNf'
        'X2BtfICBh5KanaGahHBnZmNhbHd7g5OkqaWdiGxdXmRnb36Eg4iWoaCakX5rZGZnZWx6gIeXqa2gkH5nW15obnJ+hoaMmqWhkoZ5'
        'aWNmamlte4aOnaytmoN0ZVxga3R2fIeLkZ2lnop8dGljZWtub3yMl6OsqZJ3a2VfYm14enyIkpefopmDc3BrZGVscXN9kqCnqaCJ'
        'b2RlY2Vven19iZien5yRfm5sbWZlbHR4gpipqqOUgGpgZWhpcHqAgoyeo52TiHpsaW1pZmt2f4mdrqqaiHhpX2VsbXF6g4iQoKaZ'
        'ioB3bWhsa2dreIaToq+okX1xaWFkb3FyeoaQl6CklIJ5dW9naWxpbXuOnaaroYh0bGllZW91dXyKl52enY98dHNwaGZsbXCAlqao'
        'pJiBbmlpaGZud3l/j56im5SJeXJycGlkanF2h56sqJqOfGtnaWtpbXh+hJOho5aLhHlxcG9qZGl1f4+jraWRg3hrZmlsbG15hYyY'
        'o6GRgn96cW1tamVpeoqYpqufiXp1bWVobG9weouVm6CbjH16enJramlobH+UoKelmIN0cW5mZmxxdH2RnZ2blIh7d3lyaGZoa3KF'
        'naeknZB/cW5uaGVsdHqDlaKelY2Ee3Z2cmdjaHB7jKOqoJSJfHBrbWllbHeBi5mjnY6Ggnx1cnBnYml2hZSlqpuLgnpxaWprZ216'
        'iJOboZmJgYB9dW5sZ2Jrfo+cpKWXhX15cWdma2tvf5CanJuUhn5/fXRqaGhmcIWZoqGekoF5dnBnZGpwdISWn5uUjoV9fXtyZ2No'
        'bHaNn6SdlY6AdnNuZmNqdXyKm6CZjYmFfnp4cGVhaXR/k6OkmY6JgHRva2ZjanqGkJyflYiEhn93c21kYWt8ipijoZWJhX9yamhn'
        'Zm1/j5abm5GGgoWAdG1pZGRvhJSboJ2RhoF9cWZlZ2pzhJaamJWOhYGCf3JoZmZpdYubnZuYj4R9eXBjYmlweoqbnZSOi4aBf3xv'
        'ZGRpcH2Rn52Wk42EenNtYmFrd4OPnJyQiYmHgXt2bWJibHiGlaCdko6Mg3ZtaWNibn6LlJqZjoaIiIF3cGtiY3GBjpedm5CLiYFz'
        'aGVlZXKFkpeWlI2Fhod/c2poZWZ3iZSYmZiQiIZ+b2RiZ2x4i5iYko+Nh4WFfG9lZWltfJCYl5WVkYeAeWxhYGp0f5Cal46LjYmD'
        'gHhsY2RtdoKTmpaSkpGGenNpYGFtfYeSmZWMiYyLgXpzaWJlcn+IlJqWkZCQhXRsZmFkcoSPk5aTi4iLi39zbmhjaHeHjZKXlpGO'
        'jIFvZWRkaXiKlJKRkIyJiYh9bmloZ218jJKRlZaSjYZ8a2BjaHB+jpeSjY6OioeDeWtkaGx0gY+UkJKXk4qAdmleYm54hJCWkYqN'
        'kIuDfHVpYmlye4WQlZGRlpOHeW9mX2RzgYqRlJGKjJCLf3ZwaWNreIGIj5STkpWRgnJoZWJneYiOkJCQjIuOiXtwa2lnbn2Hio6T'
        'lpOSjX1sY2Rnbn2NkY6NkI+Mi4V3bGhqbHKBi4yNk5iVjYZ4aGBkbXWCj5KNi5CSjIWAdGlma3J4goyNjpOZlol9cmVgZnN+hY+R'
        'jYuQkouAeXFoZm14fYOMj5CUmZSEdW1kYWl4hImNkI6NkJGJe3NvaGhwfIKEi5GTlpaQf25nZWVufYmLio6Qj4+NhXdtbGtrdH+G'
        'hYqUmJaSiXlpY2dqc4GLjYmNk5GNiIB0ampucHeBh4iLlZuWjYF0ZmFpcXmDjI2KjZSTi4J6cWlpcXV6gYeKjZeclIZ5b2Via3d/'
        'hYuNjY6Uk4d8dXBqanR6fYGIjpKXm5F/cmpmZW58g4aJjpCQkpCDd3FubGx1fn+BiJKXmJaMeWxnaGpxgIeGiI+Tko+LgHNtbm9w'
        'dn+BgoqVm5eQhXVoZmpvdoGIiImQlpOLhHxwa25ydHh/g4WNmZ2ViH5xZmVtdXqBiYqLkpeTh314cGtudXh5foWJkZqckYF2bmZm'
        'cHl+gYiNj5OVkIN3dHBscHd7en2Hj5WamIx7cGxoaXJ9gYKHkJOTkot/c3Fxb3F4fHx+ipWZmJOGdmtqa211foOEiJOXko2Ge3Fu'
        'cnNzeHx+gY2am5SMgHNpaW9xd3+Eh4uUmJGHgHhxbnJ2dXd8gYeQnJuQhHtxaWlxdnl/hYuPlZiOgnt2cW5yeHd2fISNlJuZi351'
        'b2pqc3p7f4ePk5SUi312dHNwcnh4d32Jk5iYlYd4cW5sbXN8fYCKk5aTjod6c3N0c3N3enmAjZiZlI6DdG5ub3B0fICDjJaYkYiC'
        'eXJydXV0dXp9hJKbmZCHf3NsbnFzdXyDh4+Yl42CfXhycnZ2dHR7gomVnJeLgHpya21ydXZ8h42Sl5SKfnl4c3J1d3V0fIiQlpqU'
        'h3t2cmxuc3d4foqTlZSQhnt2d3VydHd1dn+NlZeWj4N4c3JvbnN4e4GNl5aQi4J5dHZ3dHN1d3qDkZmWkIqAdnBxcW9zeX+GkJmW'
        'jIV/eXR1eHVydHl/iJSblIuFfXVvcHJwc3uEjJOYlIiAfXl1dHd2cXR8hY6VmZKHgHt0b29zcnR9iZGVlZCFfHp5dnR1dnJ0gIuS'
        'lZWPg3x5dG9ucnV2gI6VlZGMg3p4eXd0c3V0d4SRlpSQjIJ5d3RwbnF3e4SSmJSMhoF5d3l3dHF0d3yIlJeSjIiBd3RzcG5xeYGJ'
        'lJiSiIJ/enZ4d3Nwc3uDjJWWj4iEf3dycnBucXyIj5SWj4V/fnt2dnZzcHSAiY+UlI2FgX53cHBwcHSAjZOTkouCfXx8d3R0c3J3'
        'hI+SkpGLg357dm9tcHJ4hJKWko2IgXx6e3dycnN1fIiSk4+NiYJ8eHVvbHB2fomUl4+IhYF8eXl3cXB0eYGLk5ONioiBenZzb2tx'
        'e4SOlJWNhYKAfHh3dnFvdn+GjpKSi4eGgXlzcW9scoCLkZOSi4OAgHx3dXRxcHiEi4+QkIuFg393cG5vb3aFkJORjomCfn98dnNy'
        'cnN7iI+Pjo2LhIB9dm5sb3R7iZOTjoqHgn19e3VxcHR4gIuRj4yLioR9enRta3B5goyUk4yHhYN9enl0b3B2foSMkY6KiYmDe3Zy'
        'bGtyf4iOk5GKhYOCfXh3dG9xeYOIjI+OioiHgnlycGxtdoSOkJCOiYSCgX12c3Nwc32HjIuNjYqHhYB3bm1ucXuIkZCNjIiDgH98'
        'dHByc3eAio2Li42LhoJ9dWxrcHaAi5KQiomIg399enNucXd8hIuNi4mMi4V+eXJranN9hY2Rj4mHh4N9endzbnJ7gYaKjYuJi4uD'
        'e3Vwa2x2g4mNj46JhYaDfHd0cnB0foWIiYuMiomJgndxbm1veoeNjY2MiYWEgnp0cnJzd4GIiYiKjYuIhn90bWxvdX6Kj4yLi4qF'
        'gX95cnByd3uDiomIio2MhoF8cmtscnuCi4+MiYqKhX58d3FvdHuAhImKiIqNjIV9eHBqbXaAhouOjImJiYR8eHVxcHZ+g4WHioqL'
        'jYuDeXNva3B6hYmKjIyJiIeCenRzcnJ4gYaFhoqMi4uIgHVvbm5zfoiLiYuNioeEgHlycXN1e4OHhoWLjoyJhX1zbG5yeIGJi4mK'
        'jYuFgX13cHB1en6DhoaGi4+MhoB5cGtud32DiYuKioyLhH55dXBweH6Ag4aHiIuPjIN8dW9scHuBhYiLi4qLioJ6dnNxcnqBgoKF'
        'iYuMjYqAd3JvbnN+hYaIi42LiYeAd3Nyc3Z7g4SChYqNjYuHfXNvb3J3f4eHh4uOjIeDfnVxcnZ5fYKEg4aMj42Ig3pxbXB2e4GH'
        'iIiMjoyFf3t0cHN4fX+BhIWHjZCMhH54b21yeX6ChoqKjI6Kg3t3dHF0e3+AgISHiY6PioF5dXBudXyBgoaLjIyMiIB4dHRzdn2B'
        'gICEioyNjYd+dXJxcXd+goOGjI+MiYV+dnJ0dnh+gYGBhY2OjIqEe3JwcnV5f4OFh42QjIaBe3RxdXl7foGCg4eOkIuGgHhxb3R4'
        'e4CEh4qNkIuDfXh0cnZ8fX2Ag4WJjpCJgnx2cXB1e31/hYmMjo6JgHl2dHN3fX99f4SJjI6Oh354dHJyd31+gIaMjo2Lhn12dXV2'
        'eX2Afn+GjI6Ni4V7dXNzdHh9gIGHjpCNiIN7dHN2eXp9f3+BiI6Oi4eCeXNzdXd5fYKEiY+Qi4R/enRzeHt8fH+BhIqPjomDfnhy'
        'c3d5en2DiIuQj4mBe3h0dHl9fHx+hIeLj42HgHt3c3N4ent+hYuNj42Gfnh2dnZ6fX18f4aLjI2LhH14dnR0eHt8f4eOj42Kg3t2'
        'dXh4en19fYGIjo2LiIJ6dnZ2dXh8foKJkJCLhoB6dXV5enp8fX+Dio+NiIWAeXV1d3d3fIGGjJCQiIJ9eHV2enx6e36ChouPjIaB'
        'fnh1dXh4d32EiY6PjoZ+e3h2d3p8enqAhYmMjYuEfnx4dXV4eXl+h42PjouEfHh4d3h6fHt7gYmMjIuJgnx6eHZ1d3l7gIqQj4uH'
        'gnp2eHl5eXt8fYOLjYuJhoF6eHh3dXZ6f4SMkY6Jg396dnh6enl6foGGjI6KhoN/end4d3V2e4KIjZCNhoB9enZ4e3p4en+FiIyN'
        'iYSAfnp2d3d2d32GjI6Pi4R9e3p4eHp6eXuCiIqLi4iCfnx6d3Z3dnmAiY+OjIiCe3l6eXh5enp9hIqMiomGgX17end0dnh8g4yQ'
        'jYmFgHp4enp4d3p8gIaMjImGhYB8enp3dHV6gIeNkIyGgn96eHl6eHd6f4OIjIyIhIOAe3l4d3R1fYSKjo6LhH9+enh5enh3e4KH'
        'iYuKh4KBf3t4d3Z0d4CIjI2MiYJ9fHt5eHh5eX2FiYqJiYaBf357d3V1dnqDi46MioaBfHt7eXd3eXt/h4uKiIeFgX59e3ZzdXl+'
        'hY2Oi4eEgHt6e3l2d3p/g4iLioaFhIF9e3p1cnV8g4iNjomFgn98eXp5dnd8goaIiomFhIOBfXl4dXN3f4eKjI2Ig4B+fHl4eHd4'
        'foWIiImIhYOCgHx4dnR0eYKKjIuKh4J/fXx5dnd4eoCHiYiHh4WCgX97dnN1d32Fi4yKiIaBfXx7eHV3en2CiIqIhoaFgn9+enVy'
        'dnuAh4yMiYaFgX17enh1dnyBhIiJh4WFhYJ+fHh0cnd/hImMi4iEg4F8enl3dXh/hIaHiIeFhISCfXl2dHR5goeJioqHg4GAfHh3'
        'd3d6gYeHhoeHhYODgXt3dHR2fIWKiYmJh4J/f3x3dXd5fYKIiIaGhoWDgYB6dHN1en+Gi4qIiIaCfn17dnR3fICEh4iFhYaFg4B9'
        'eXNzd32Ch4qKh4aFgn17eXZ0eX+DhYaIhoWGhYJ+endzdHqBhYeKioeFhIF9eXd2dnqBhYWFh4aFhYWCfHh1dHZ8g4eHiImHhIKA'
        'fHd1d3h9g4aGhYaHhYSEgHp1dHZ4f4WIiIiJh4OBfnp2dHh7f4SGhoSFh4aDgn54c3R4fIGGiIiHiIeDf3x5dXR5f4GEhoaFhYeG'
        'gn98d3N0en+ChoiIh4eGgn16d3V2e4GDhIWGhYWGhoJ9eXZ0dnyChIaIiYeGhYF7d3Z2eH2DhYOEhoaGhYWAend1dXh+hIWFiImI'
        'hYOAenV1d3t/g4WEhIaHhoSDf3h1dXh7gISGhoiJiISAfnh0dXp+gYOFhISGiIaDgX13dHZ6foGEh4eHiYeDfnt3dHZ8gIKDhIWE'
        'hoiGgn56dnR3fYCChIeIh4iGgXx4d3V4foKDgoSGhoaHhYB7eHZ1eX6BgoSIiYiHhYB6dnZ3en+Dg4KEhoeGhoR/eXZ3eHp/goOF'
        'iIqIhYN+eHV2en2Ag4ODhIeIhoSCfXd1d3p8f4OEhoiKiIOAfHd1d3x/gIKEhIWHiIaCf3t3dXh8fn+DhoeIiYeCfXp2dXh+gYGC'
        'hIWGh4iFgHx5d3Z6fn+Ag4eIiYiGgHp4d3d6f4KBgYSGhoeHhH56eHd4e36AgYSIiomHhH54dnd5fH+CgoGEh4eGhYJ9eHd5enx+'
        'gYKFiYqIhYF8d3V4fH5/gYKDhYiIhoOAfHd3ent8foKEhomLh4N+end2eX5/f4GDhIWIiIWBfXp3d3t9fX6ChoiJioaAe3l3d3t/'
        'gH+BhIaGh4eDf3t6eHh7fX1/g4iJiYiFfnl3eHl7f4CAgYWHh4aGgn16eXp6e35+gISJioiGgnx4d3l7fH+AgYKGiIiFhIB7eXl7'
        'e3t9gIKGiouIg4B7d3d6fX1+gYKEhoiIhIF/e3h5e3x7fYGEh4qKh4F9end4e35+foGEhYeIh4N/fXt5enx8e36Dh4mKiYV/e3l4'
        'eXx+fn6BhYeHh4aCfXt7enp7fH1/hImJiYeDfXl5enp8fn9/goaIh4aEgXx6e3t6e3x+gYaKioiFgXx4eXt8fH6AgYOHiIeEgn97'
        'ent8enp8gIOHi4qGgn57eHl8fHx9gIOFh4iGg4B+fHp7fHp6fYKGiIqJhYB8enl5fH18foGFhoeIhYF+fXx7e3t7e36EiImJiIN+'
        'e3p6enx9fX+DhoeGhoSAfXx8e3p7e3yAhomJiIaBfHp6e3t7fX6AhIeIhoSDf3x8fHx6enx+goeKiYaDgHt5enx7e32AgoWIiIWC'
        'gX98fHx8eXl9gYSIiomFgX57eXp8fHt9goSGh4eFgX9+fHx8e3p6foOGiImIg399e3p6e3x8foOGhoeGhIB+fn17e3p6e4CFiIiI'
        'hoJ9fHx7ent8fYCEh4eGhYN/fX5+e3p6e32Bh4mIh4SBfHt8e3p6fH+ChYiHhYOBf319fXt5eXyAg4eKiIWCf3x7e3t6en2BhIaH'
        'h4SCgH99fX17eHp+goWIiYeDgH58e3t7ent+g4WGh4aDgH9/fnx7enl7gISHiIiGgn9+fXt6ent8gISHhoWFgn9/f357enp6fIGG'
        'iIeHhYF+fX17eXp8foGFh4aEg4J/fn9+e3h5fH6Dh4iHhYSAfXx8e3l5fYCDhoeGg4KBf35+fXp4en6BhIeIhoSCgH18e3p5en6D'
        'hIaHhYOBgYB+fXx5eHuAg4WHiIaDgIB9e3p6enuAhIaGhoWCgICAfnx6eXl8gYWGh4eFgn9/fXp5eXt9gYWGhYWEgoCAgH56eXl7'
        'foKGh4aGhIF/fn16eHp8f4OGh4WDg4KAf399eXh6fYCDh4eFhIOBfn18eXh6foKEhoaFgoKCgH9+fHl4e3+ChIaHhYOCgX58enl4'
        'e4CDhYWGhIKBgYB+fHt5eX2Bg4WGh4WCgoB+e3l5en2ChYWFhYSCgYGAfnt5enp+goWFhYaFgoGAfXp4eXx/g4WFhISDgoCBgH15'
        'eXt9f4OFhoWFhIKAfnx5eHp+gYOGhYSDg4KBgH98eXl8f4GDhoaFhISCf317eHh7gIKEhYWEgoKCgX99e3l5fYCChIaGhYODgX57'
        'enh5fYGEhISFg4KCgoF9e3p5e36Cg4SFhoWDgoF9eXl5e36ChYSEhIOCgYKAfHp6enx/goSEhYaFg4F/fHh4en2Ag4WEg4ODgoGA'
        'f3t5enx+gIOFhISFhYKAfnt4eHx/gYOFhYODg4OBf317eXp9f4GDhYWEhYSCf3x6eHl9gYKDhIWDgoODgH58enl7f4GCg4WFhISE'
        'gX16eXl6foKDg4SEhIKDgoB8enp7fH+CgoOFhoWDg4B8eXh6fH+DhIODhISDgoF/e3p6fH2AgoODhIaFg4F/e3h5fH6Ag4SDg4SE'
        'g4GAfXp5e31/gIKDhIWGhYJ/fXp4eX2AgYOEhIODhIOAfnx6enx+gICChISFhYWCfnt5eXt+gYKChISDg4ODf3x7ent9f4CBgoSF'
        'hYWEgXx5eXp8f4KDgoOEhIODgn57ent8fX+BgYKFhoWEgn97eHp8fYCCg4ODhISDgoB9enp8fX5/gYKDhYaFg4B9enh6fX+AgoOD'
        'g4SEg4F/fHp6fX5+f4GDhIWGhYJ/fHp5e36AgYKDhIOEhIJ/fXx7e31/f4CChIWFhoSBfXp6enx/gYGChISEhISCfnx7fHx9f4CA'
        'goSGhYWDf3t5ent9f4GCgoSFhIOCgH17e319fX+AgYOFhoWEgX56eXt9fn+BgoOEhYWDgX98e3x9fn5/gYKDhYaFgn99enl8fn9/'
        'goODhIWEgn9+fHt8fn5+f4GDhIaGhYF9e3p6fH5/gIKEhISEhIF+fHx8fH5/f3+ChIWGhoN/fHt7e31/gICChIWEhIOAfXx8fX1+'
        'f3+AgoWGhYSCfnt6fHx9f4CBgoSFhIOBf3x7fX59fX6AgYOGhoWDgH16enx9fX+BgoOEhoSCgH58fH1+fn1/gYKEhoeEgX58e3t9'
        'fn5/gYOEhIWEgX59fXx9fn59f4GDhYaGg4B9fHt7fX5/f4KEhYSEg4B9fX19fX5+fn+ChYWFhYJ+fHx8fH1+f4CChYWEg4J/fHx9'
        'fn19fn+Ag4WGhYOBfXt8fH19foCBg4WFhIKAfnx8fn59fX6AgYSGhoSCf317fH19fX6Bg4SFhYSBf359fX5+fX1/gYOEhoaDgH59'
        'fHx9fX1/goSEhYWDgH5+fX19fn19f4KEhYaFgn99fXx8fX1+gIKFhYSEgn99fX59fX19foCDhYWFhIF+fH19fHx+f4GDhYWEg4F+'
        'fX1+fnx9fn+BhIaFhIKAfnx9fXx8foCChIWFg4GAfn19fn58fX+AgoSGhYOBf318fH18fH+Bg4SFhYOAf35+fX59fH1/goOFhoWC'
        'gH9+fXx8fX1/goSFhYSCf35+fn19fX19gIOEhYWEgX9+fn18fH1+gIOFhYSDgX5+fn59fH1+foGEhYWEg4F+fn59e3x+gIGEhYWD'
        'gYB+fn5+fXx9foCChIWFg4KAfn19fHt8foGChIWFgoB/f35+fn18fX+BgoSFhIKAgH59fXx8fH+ChISFhIJ/f39+fn19fH2AgoOE'
        'hYSBgH9+fXx8fH2Ag4WEhIOBf39/f319fX1+gYOEhISDgX9/fnx7fH1/gYSFhIOCgH9+f359fH1+f4GEhYSDgoB/fn58e3x+gIKE'
        'hYSCgYB/f35+fHx9f4GChIWEgoGAf359fHt8f4GDhIWEgYCAf39+fXx8foCCg4SEg4GBgH99fHx7fYCDhISEg4F/gH9+fX19fX6B'
        'g4OEhIOBgIB/fHt7fH6BhISEg4KBf39/fnx8fX5/goOEg4ODgYCAfnx7fH5/goSFhIKBgX9/f358fH1/gIKEhIOCgoGAf317e3x/'
        'gYKEhYOCgYGAf359fHx+gIGChISDgoKBf358e3t9gIKDhISDgYCAgH59fXx9f4GCgoOEgoKBgX98fHt8foGDhISEgoGAgIB+fHx9'
        'fX+Bg4ODg4KBgYB+fHt8fX+ChISDg4KBgIB/fXx8fX6AgoODg4OCgYF/fXt6fH6AgoSEg4KCgYB/fn18fH5/gYKDg4KCg4GAfn17'
        'e32AgYOEhIOBgYGAf319fH1/gIGCg4OCgoKBf318e3t+gYKDg4OCgYGBgH59fH19f4GCgoODgoKCgX58e3x9f4GDg4ODgoGBgX99'
        'fHx9foCCgoKCg4OCgYB9e3t8fn+Cg4ODgoKBgIB/fHx9fn+AgoOCgoODgoB/fXt7fX+AgoSDgoKCgYB/fnx8fX+AgYKDgoKDg4J/'
        'fnx7fH6AgYKDg4KCgoGAfn18fH6AgYGCg4OCg4OBfnx8e3x/gYKCg4OCgoKBf318fX1+gIGBgYKDg4KCgH57e3x9f4GDg4ODgoKB'
        'gH58fH1+f4CBgoKCg4OCgX99e3x9foCCg4OCg4OCgH9+fHx+f3+AgYKCgoODgoB+fHt8fn+AgoODgoKDgYB+fXx9foCAgIGCgoKD'
        'g4F/fXx8fH+AgYKDg4KCgoF/fX19fX6AgYGBgoODg4OAfnx8fH1/gYGCg4ODgoKAfnx9fX5/gIGBgYKDg4OCgH18fH1+f4GCgoOD'
        'g4KBgH18fX5/f4CBgYGCg4OCgX98e3x+f4CBgoKCg4OCgH59fH1+f4CAgYKCg4SDgX9+fHx9fn+AgYODg4ODgX99fX19f4CAgIGC'
        'goOEg4B+fXx8fX+AgYGDg4ODgoB+fX19fn+AgICBgoODg4KAfXx9fX5/gIGCg4ODgoF/fXx9fn5/gICBgYODg4KBf318fX5+f4GC'
        'goOEg4KAf318fX9/f4CBgYKDhIOBgH59fH1+f3+BgoKDhIOBf359fX5/f3+AgYKCg4SDgH9+fX19f3+AgYKDg4ODgH59fX1+f4B/'
        'gIGCg4ODgoB+fX19fn+AgIGDg4ODgoB9fX5+fn+AgICBg4ODg4F/fX19fX5/gIGCg4SDgoF/fX1+f39/gICAgoOEg4KAfn19fn5+'
        'f4GBgoOEg4F/fn19fn9/f4CBgYKDhIKBf359fX5+fn+BgoODhIKAfn5+fX5/f3+AgYKCg4OCgH5+fX1+fn+AgYODg4OCf359fn5+'
        'f39/gIGDg4ODgX9+fn59fn9/gIKDhIOCgX99fX5+fn9/gICCg4ODgoB/fn5+fX5/gIGCg4SDgYB+fX5+f35/gICBgoODgoGAfn5+'
        'fn5+f4CCg4SEgoB/fn5+fn9/f4CBgYKDg4KAf35+fX5+fn+BgoOEg4J/fn5+fn5/f3+AgYKDg4OBf39+fn1+fn+AgoODg4OBf35+'
        'fn5+f39/gIKDg4OCgX9+fn59fX5/gIKEhIOCgH9+fn9+fn9/gIGCg4OCgYB/fn5+fX1/gIGChISCgX9/fn5/fn5/gIGBgoODgYCA'
        'f35+fn1+f4GCg4SDgoB/f35+fn5+f4CBgoODgoGAf39+fn5+fn+Bg4ODg4F/fn9/fn5/f3+AgoODg4KAf39/fn19fn+AgoODg4KA'
        'f35/f35+f3+AgYKDg4KBgH9/f359fX5/gYKEhIKBgH9+f39+fn9/gIGCg4KBgYB/f35+fX1/gIGDhIOCgIB/fn5+fn5/gIGCg4OC'
        'gYCAf35+fn1+f4GCg4ODgX9/f35+fn5+f4CCgoODgoCAgH9+fX1+foCCg4ODgoF/f39+fn5+f3+BgoKCgoGAgIB/fn19fn+AgoOD'
        'goGAf39/fn5+fn+AgYODgoGBgIB/f359fX+AgYOEg4KBgH9/f35+fn+AgYGDg4KBgYCAf359fX5/gYKDg4OBgIB/f35+fn5/gIGC'
        'goKBgYCAgH5+fX1+gIGCg4OCgYCAf35+fn5+f4GCgoKCgYCAgH9+fX1+f4CCg4OCgoCAf39+fX5+f4CBgoKCgYGAgIB/fn19fn+B'
        'g4ODgoGAgH9/fn1+f4CAgoKCgYGBgYB/fn19fn+AgYODgoGBgIB/fn59fn+AgYKCgoGBgYGAf359fX6AgYKDg4KBgIB/fn5+fn6A'
        'gYGCgoKBgYGBf359fX1+gIKCg4KCgYCAf359fn5/gIGCgoKBgYGBgH9+fX1+f4GCg4KCgYGAgH9+fX5/f4CCgoKBgYGBgIB/fX1+'
        'f4CBgoOCgYGBgH9/fn1+f4CBgoKCgYGBgYB/fn19fn+AgYKDgoGBgYB/fn59foCBgYGCgYGBgYGAfn59fX6AgYKCgoKBgYF/fn5+'
        'fn+AgYGBgYGBgYGBf359fX5/gYKCgoKCgYGAf359fn5/gIGCgYGBgYGBgH99fX5+f4GCgoKCgoGAgH99fX5/gIGCgoGBgYKBgH9+'
        'fX1+f4CBgoKCgoKBgH9+fX1+gICBgYKBgYGCgYB/fn19f4CBgYKCgoGBgX9+fn5+f4CBgYGBgYGBgoF/fn59fn+AgYGCgoKBgYB/'
        'fn5+fn+AgYGBgYGBgYGAfn5+fn5/gYGBgoKCgYGAfn19fn+AgYGBgYGCgoGBgH59fn5/gIGCgoKCgoGAf359fX9/gIGBgYGBgoKB'
        'gH9+fX5/f4CBgoKCgoKBgH5+fX5/gICBgYGBgYKCgX9+fn1+f4CAgYKCgoKCgX9+fn5+f4CBgYGBgYGCgYB/fn5+fn+AgYGCgoKC'
        'gYB+fX5+f3+BgYGBgYKCgYGAfn5+fn9/gYGBgoKCgYF/fn1+f3+AgYGBgYGCgoGAf35+fn9/gIGBgYKCgoGAf359fn+AgIGBgYGB'
        'goKAf39+fn5/f4CBgYKCgoKBf35+fn5/gICAgYGBgoKBgH9+fn5+f4CAgYKCgoKCgH5+fn5/f4CBgIGBgoKCgYB+fn5+f3+AgIGC'
        'goKCgYB+fn5/f4CAgYCBgoKCgYB/fn5+f39/gIGBgoOCgYB/fn5+f3+AgIGBgYKCgoGAf35+f39/gICBgYKDgoF/fn5+fn+AgICB'
        'gYGCgoGAf39+fn9/f4CAgYKCgoKAf35+fn5/gICAgYGCgoKBgH9/f35/f4CAgYKCgoKBgH5+fn9/gICAgIGCgoKBgH9+fn9+f3+A'
        'gIGCg4KBgH9+fn5/f4CAgIGBgoKBgYB/fn5/f39/gIGBgoOCgYB/fn5+f3+AgIGBgYKCgYB/f35+f39/f4CBgoKDgoB/f35+f3+A'
        'gICBgYKCgoGAf39/fn9/f3+BgoKCgoGAf35+fn9/gICAgYKCgoGAf39/f35/f3+AgYKCgoKBf35+f39/f4CAgIGCgoGBgH9/f39/'
        'f3+AgIGCg4KBgH9+fn9/f3+AgIGBgoKBgIB/f39/f39/gIGBgoOCgH9/fn5/f39/gIGBgoKCgYB/f39/f39/f4CBgoKCgYB/f39+'
        'f39/gICBgoKCgYB/f39/f39/f4CBgoKCgoF/f39/f39/gICAgYKCgYGAf39/f35/f3+AgYKCgoGAf39/f39/f4CAgYKCgoGAgH9/'
        'f39+fn+AgIGCgoKAgH9/f39/f3+AgYGCgoGAgIB/f39/f35/gIGCgoKBgH9/f39/f39/gIGBgoKBgICAf39/f39/f4GCgoKCgYB/'
        'f39+f39/gICBgoKBgYB/gH9/f39/f4CBgoKCgYB/f39/fn9/gICBgoKBgYCAf39/f35+f3+AgYKCgYGAf39/f35/f4CAgYKCgYCA'
        'gIB/f39+fn+AgYKCgoGAgH9/f39/f3+AgYGCgoGAgICAf39/fn9/gIGCgoKBgIB/f35/f3+AgYGCgoGBgICAgH9/f39/gIGCgoKB'
        'gICAf39+f39/gIGCgoGBgYCAgIB/fn9/f4CBgoKBgYCAf39/fn5/gICBgoKBgYCAgIB/f35+f4CBgoKCgYGAgH9/f35+f4CBgYKC'
        'gYCAgIB/f39+fn+AgYKCgoGAgIB/f39+f3+BgYGCgYGAgICAf39/fn+AgYGCgoGBgICAf35+f3+AgYGBgYGAgICAgH9/f39/gIGC'
        'goGBgYCAf39+fn9/gIGCgYGBgICAgH9/fn9/f4CBgoGBgYCAf39/fn5/gIGBgoGBgICAgIB/f35/f4CBgoKBgYGAgH9/fn5/gICB'
        'gYKBgICAgIB/f39+f4CAgYKCgYGBgIB/fn5+f4CBgYGBgYCAgICAf39/fn+AgYGBgYGBgIB/f35+f3+AgYGBgYGBgICAf39+f39/'
        'gIGBgYGBgYCAf35+fn+AgIGBgYGBgYCAgH9/fn9/gIGBgYGBgYGAf39+fn9/gIGBgYGBgYGAgH9/fn5/gICBgYGBgYGBgH9/fn5/'
        'gIGBgYGBgIGBgIB/f35+f4CBgYGBgYGBgIB/fn5/f4CBgYGBgYGAgYB/f39/f3+AgYGBgYGBgYB/fn5+f4CAgYGBgYGBgICAf35/'
        'f3+AgYGBgYGBgYCAf35+f3+AgYGBgYGBgYCAgH9+fn9/gIGBgYGBgYGAf39+fn+AgIGBgYGBgYGAgH9/fn9/gICBgYGBgYGBgH9+'
        'fn5/gIGBgYGBgYGBgH9/f39/f4CBgYGBgYGBgH9+fn5/f4CBgYGBgYGBgIB/f39/f4CAgYGBgYGBgYB/fn5/f4CBgYGBgYGBgICA'
        'f39/f3+AgYGBgYGBgYCAf35+f4CAgYGBgYGBgYCAf39/f3+AgICBgYGBgYGAf39+fn+AgIGBgYGBgYGAf39/f3+AgICAgYGBgYGA'
        'f39/fn9/gIGBgYGBgYGBgH9/f39/gICAgIGBgYGBgH9+fn9/gICBgYGBgYGBgIB/f39/f4CAgICBgYGBgIB/fn5/f4CAgYGBgYGB'
        'gIB/f39/f4CAgIGBgYKBgYB/f35+f4CAgIGBgYGBgYB/f39/f4CAgICBgYGCgYCAf39+f3+AgICBgYGBgYGAf39/f3+AgICAgYGB'
        'gYGAf39/f3+AgICAgYGBgYGAf39/f39/gICAgIGBgYGBgH9+f39/gICAgIGBgYGAgH9/f39/f4CAgICBgoGBgH9/fn9/gICAgYGB'
        'gYGBgIB/f39/gICAgICBgYKBgIB/f35/f4CAgIGBgYGBgYB/f39/f4CAgICBgYGBgYB/f39/f4CAgICBgYGBgYB/f39/f3+AgICA'
        'gYGBgYGAf39/f3+AgICAgYGBgYGAf39/f39/gICAgIGCgYGAgH9/f39/gICAgIGBgYGAgH9/f39/f4CAgIGBgoGBgH9/f39/f4CA'
        'gYGBgYGAgIB/f39/gH+AgIGBgYKBgIB/f39/f4CAgIGBgYGBgIB/f39/f4B/gICBgYGBgYB/f39/f4CAgICBgYGBgYB/f39/f3+A'
        'gICAgYGBgYCAf39/f3+AgICAgYGBgYCAf39/f39/gICAgYGCgYGAgH9/f39/gICAgYGBgYCAgH9/f39/f4CAgIGBgoGAgH9/f39/'
        'f4CAgYGBgYGAgIB/f39/f3+AgIGBgYGBgIB/f39/f4CAgIGBgYGBgH9/f39/f39/gICBgYGBgIB/f39/f3+AgICBgYGBgYB/f39/'
        'f3+AgICBgYGBgYCAf39/f39/gICBgYGBgYCAf39/f39/gICAgYGBgYCAgH9/f39/f4CAgYGBgYCAgH9/f39/f4CAgYGBgYGAgIB/'
        'f39/f3+AgYGBgYGAgIB/f39/f3+AgYGBgYGAgICAf39/f3+AgIGBgYGBgICAf39/f3+AgIGBgYGBgIB/gH9/f3+AgIGBgYGBgIB/'
        'f39/f39/gICBgYGBgICAf39/f39/gICBgYGBgICAf39/f39/gICBgYGBgICAgH9/f39/f4CBgYGBgYCAgIB/f39/f4CAgYGBgYCA'
        'gIB/f39/f4CAgYGBgYGAgICAf39/f3+AgYGBgYGAgICAf39/f3+AgYGBgYGAgICAgH9/f3+AgIGBgYGBgICAgH9/f3+AgIGBgYGB'
        'gICAgH9/f3+AgICBgYGBgICAgIB/f39/gICBgYGBgICAgH9/f39/gICBgYGBgICAgH9/f39/gICBgYGBgICAgIB/f39/f4CBgYGB'
        'gYCAgIB/f39/f4CBgYGBgYCAgICAf39/f4CAgYGBgYGAgICAf39/f4CAgYGBgYGAgICAf39/f3+AgIGBgYGAgICAgH9/f3+AgIGB'
        'gYGAgICAgH9/f3+AgIGBgYGAgICAgH9/f3+AgICBgYGAgICAgH9/f39/gICBgYGBgICAgH9/f39/gICBgYGBgICAgIB/f39/gICB'
        'gYGBgYCAgIB/f39/f4CBgYGBgYCAgIB/f39/f4CAgYGBgYGAgICAf39/f4CAgYGBgYGAgICAf39/f4CAgYGBgYGBgICAf39/f4CA'
        'gIGBgYCAgICAgH9/f3+AgIGBgYGAgICAgH9/f3+AgICBgYGAgICAgH9/f3+AgICBgYGBgICAgH9/f39/gICBgYGBgICAgH9/f39/'
        'gICBgYGBgYCAgIB/f39/gICBgYGBgYCAgIB/f39/gICAgYGBgYGAgIB/f39/gICAgYGBgYGBgICAf39/f4CAgYGBgIGBgICAf39/'
        'f4CAgIGBgYGBgYCAf39/f4CAgICBgYGBgYCAf39/f3+AgICBgYGBgYCAf39/f3+AgICAgYGBgICAgH9/f3+AgICAgIGBgYCAgH9/'
        'f3+AgICAgIGBgYCAgH9/f39/gICBgICBgYGAgIB/f39/gICAgYCBgYGAgIB/f39/gICAgYGAgYGBgIB/f39/gICAgIGBgYGBgICA'
        'f39/gICAgICBgYGBgYCAf39/f4CAgICBgYGBgYCAf39/f4CAgICAgYGBgYCAf39/f4CAgICAgYGBgYCAf39/f3+AgICAgIGBgYCA'
        'gH9/f3+AgICAgIGBgYCAgH9/f3+AgICAgICBgYGAgH9/f3+AgICAgICBgYGAgIB/f3+AgICAgICBgYGBgIB/f39/gICAgICBgYGB'
        'gIB/f39/gICAgICBgYGBgIB/f39/gICAgICBgYGBgYB/f39/f4CAgICAgYGBgYCAf39/f4CAgICAgYGBgYCAf39/f4CAgICAgIGB'
        'gYCAgH9/f4CAgICAgIGBgYCAgH9/f4CAgICAgIGBgYCAgH9/f4CAgICAgICBgYGAgIB/f3+AgICAgIGBgYGAgIB/f3+AgICAgIGB'
        'gYGBgIB/f39/gICAgICBgYGBgIB/f39/gICAgICBgYGBgIB/f39/gICAgICBgYGBgICAf39/gICAgICAgYGBgICAf39/gICAgICA'
        'gYGBgICAf39/gICAgICAgIGBgYCAgH9/f4CAgICAgIGBgYCAgH9/f4CAgICAgIGBgYGAgIB/f4CAgICAgIGBgYGAgIB/f3+AgICA'
        'gIGBgYGAgIB/f3+AgICAgIGBgYGAgIB/f39/gICAgICBgYGBgIB/f4B/gICAgICBgYGBgICAf3+AgICAgICAgYGBgICAf3+AgICA'
        'gICAgYGBgICAf3+AgICAgICAgYGBgICAgH9/gICAgICAgYGBgYCAgIB/f4CAgICAgYGBgYCAgIB/f4CAgICAgYGBgYCAgICAf3+A'
        'gICAgIGBgYGAgICAgH+AgICAgIGBgYGAgICAgIB/gICAgIGBgYGAgICAgIB/f4CAgICBgYGAgICAgICAf4CAgICBgYGAgICAgICA'
        'gH+AgICAgYGBgICAgICAgH+AgICAgYGBgICAgICAgIB/gICAgYGBgICAgICAgICAgICAgYGBgYCAgICAf4CAgICAgYGBgYCAgICA'
        'gH+AgICAgYGBgYCAgICAgH9/gICAgIGBgYCAgICAgIB/f4CAgIGBgYCAgICAgIB/f4CAgICBgYCAgICAgICAf3+AgICBgYGAgICA'
        'gICAf3+AgICBgYGAgICAgICAf3+AgICBgYGBgICAgICAgH9/gICBgYGBgICAgICAf39/gICAgYGBgICAgICAf3+AgICAgYGBgICA'
        'gICAf39/gICAgYGBgICAgICAgH9/gICAgIGBgICAgICAgH9/f4CAgIGBgYCAgICAgIB/f4CAgIGBgYCAgICAgIB/f4CAgICBgYCA'
        'gICAgIB/f3+AgICBgYGAgICAgIB/f3+AgICBgYGAgICAgIB/f3+AgICBgYGAgICAgIB/f3+AgICBgYGAgICAgICAf3+AgICAgYGA'
        'gICAgICAf39/gICAgYGAgICAgICAf39/gICAgYGBgICAgICAgH9/gICAgIGBgICAgICAgH9/f4CAgIGBgICAgICAgIB/f4CAgICB'
        'gYCAgICAgIB/f4CAgICAgYCAgICAgH9/f3+AgICAgICAgICAgIB/f3+AgICBgICAgICAgIB/f3+AgICBgICAgICAgIB/f3+AgICA'
        'gYCAgICAgICAf3+AgICAgYCAgICAgICAf39/gICAgIGAgICAgICAf39/gICAgIGAgICAgICAgH9/gICAgICAgICAgICAgH9/f4CA'
        'gICAgICAgICAgH9/f4CAgICAgICAgICAgH9/f4CAgICAgICAgICAgH9/f4CAgICAgICAgICAgIB/f4CAgICAgICAgICAgIB/f4CA'
        'gICAgICAgICAgIB/f3+AgICAgICAgICAgICAf3+AgICAgICAgICAgICAf39/gICAgICAgICAgICAf39/gICAgICAgICAgICAf39/'
        'gICAgICAgICAgICAf39/gICAgICAgICAgICAgH9/gICAgICAgICAgICAgH9/gICAgICAgICAgICAgH9/f4CAgICAgICAgICAgIB/'
        'f4CAgICAgICAgICAgIB/f4CAgICAgICAgICAgICAf3+AgICAgICAgICAgICAf3+AgICAgICAgICAgICAf3+AgICAgICAgICAgICA'
        'f3+AgICAgICAgICAgICAf3+AgICAgICAgICAgICAf3+AgICAgICAgICAgICAgH9/gICAgICAgICBgICAgH9/gICAgICAgICBgICA'
        'gIB/gICAgICAgICAgICAgIB/f4CAgICAgICAgICAgICAf4CAgICAgICAgICAgICAf4CAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgYCAgICAf4CAgICAgICAgYGAgICAf4CAgICAgICAgIGAgICAgH+AgICAgICAgIGBgICAgH+AgICAgICAgICB'
        'gICAgIB/gICAgICAgICBgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICB'
        'gICAgICAgICAgICAgICAgYCAgICAgICAgICAgICAgYCAgICAgICAgICAgICAgYGAgICAgICAgICAgICAgIGAgICAgICAgICAgICA'
        'gIGBgICAgICAgICAgICAgICBgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICBgICAgICAgICAgICA'
        'gICBgICAgICAgICAgICAgICBgYCAgICAgICAgICAgICAgYCAgICAgICAgICAgICAgYGAgICAgICAgICAgICAgIGAgICAgICAgICA'
        'gICAgIGAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGAgICAgICAgICA'
        'gICAgICBgICAgICAgICAgICAgICBgICAgICAgICAgICAgICAgYCAgICAgICAgICAgICAgYCAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIGAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICA'
        'gICAgICAgICAgICAgICAgICAgA=='
    )


# ---- display.py ----
"""Buffered 135x240 display: anchored decimal glyphs, tall bar, status icons."""

class VarioDisplay:
    def __init__(self,lcd):
        self.lcd=lcd
        lcd.setRotation(0)
        self.canvas=lcd.newCanvas(135,240,16,True)
        self.fonts=lcd.FONTS
        self.last_key=None
        self.frames=0
    def splash(self,version,update,sleep_ms,ticks_ms,ticks_diff,title='VibeVario',speaker=None,caption=None):
        # Draw before BLE/FIFO start. One reused canvas, no bitmap allocations.
        import math
        bg=0x101E29;white=0xF2F5EE;outline=0x9CB6CF
        c=self.canvas
        def center(label,y,size,color):
            c.setFont(getattr(self.fonts,'Montserrat%d'%size))
            self.text(label,(135-c.textWidth(label))//2,y,size,color,bg)
        def line(points,color,width=1):
            for a,b in zip(points,points[1:]):
                c.drawLine(a[0],a[1],b[0],b[1],color)
                if width>1:
                    c.drawLine(a[0]+1,a[1],b[0]+1,b[1],color)
                    c.drawLine(a[0],a[1]+1,b[0],b[1]+1,color)
            if width>2:
                for x,y in points:c.fillCircle(x,y,1,color)
        def poly(points,color):
            a=points[0]
            for b,d in zip(points[1:],points[2:]):
                c.fillTriangle(a[0],a[1],b[0],b[1],d[0],d[1],color)
        def mountains(scale,y):
            def pts(data):return [(int(67+(x-67)*scale),int(y+h*scale)) for x,h in data]
            left=pts(((7,49),(38,8),(70,49)))
            right=pts(((48,49),(85,0),(128,49)))
            poly(left,0x49637C);poly(right,0x344C66)
            poly(pts(((38,8),(26,24),(34,21),(39,25),(45,21),(51,25))),white)
            poly(pts(((85,0),(71,19),(80,15),(86,21),(94,16),(101,20))),white)
            line(pts(((7,49),(38,8),(62,36),(85,0),(128,49))),outline,3)
            line(pts(((7,49),(128,49))),outline,2)
        def wing(elapsed):
            exit_t=max(0.,min(1.,(elapsed-1900)/700.))
            dx=int(-150*exit_t*exit_t)
            # Visual metaphor follows the pitch hill, rather than integrated altitude.
            climb=math.sin(math.pi*min(elapsed,1900)/1900.)**2
            dy=int(-17*climb+34*exit_t*exit_t)
            def pts(data):return [(x+dx,y+dy) for x,y in data]
            canopy=pts(((81,49),(85,40),(94,34),(105,33),(116,37),(124,45),(126,51),(114,46),(102,44),(91,45),(81,49)))
            poly(canopy,0x438DE0)
            poly(pts(((85,40),(94,34),(105,33),(102,44),(91,45))),0xC9DCE9)
            poly(pts(((105,33),(116,37),(114,46),(102,44))),0x3268BA)
            poly(pts(((116,37),(124,45),(114,46))),0xF4D750)
            poly(pts(((81,49),(85,40),(91,45))),0xE56A99)
            line(canopy,0xBADBFA,2)
            for a,b in (((94,34),(91,45)),((105,33),(102,44)),((116,37),(114,46))):line(pts((a,b)),0x26496A)
            for x,y in ((82,49),(92,45),(113,46),(125,51)):line(pts(((x,y),(103,68))),0xB3C7D4)
            c.fillCircle(104+dx,64+dy,2,white)
            line(pts(((104,68),(101,74),(109,77),(114,73))),white,2)
            line(pts(((103,69),(98,65))),white)
        def icecream():
            # Rotate the white lemon ice clockwise, including the liquorice stick.
            angle=.22;co=math.cos(angle);si=math.sin(angle)
            def pts(data):return [(int(67+x*co-y*si),int(170+x*si+y*co)) for x,y in data]
            body=[(-18,15),(-18,-22),(-15,-32),(-8,-38),(0,-40),(8,-38),(15,-32),(18,-22),(18,15)]
            stick=[(-5,5),(5,5),(5,40),(3,43),(-3,43),(-5,40)]
            poly(pts(stick),0x03070A);line(pts(stick+[stick[0]]),0x405463)
            poly(pts(body),white)
            line(pts(body+[body[0]]),0xB9CFD9,2)
            line(pts(((-11,-20),(-11,7))),0xFFFFFF,2)
        sound=None
        if speaker is not None:
            try:
                sound=startup_wav()
                speaker.begin();speaker.stop();speaker.setChannelVolume(0,255);speaker.setVolume(160)
                speaker.playWav(sound,1,0,True)
            except Exception as e:print('E,SPLASH_AUDIO,%s'%e)
        started=ticks_ms()
        while True:
            frame=ticks_ms();elapsed=ticks_diff(frame,started)
            if elapsed>=4100:break
            update();c.fillScreen(bg)
            if elapsed<1900:
                mountains(1.,76);wing(elapsed)
                center(title,146,24,white)
                center(version,180,16,0x9FB6BF)
            elif elapsed<2600:
                t=(elapsed-1900)/700.;t=t*t*(3-2*t)
                mountains(1.-.45*t,int(76-47*t));wing(elapsed)
                if t<.55:
                    f=1-t/.55
                    rgb=[int(b+(a-b)*f) for a,b in zip((242,245,238),(16,30,41))]
                    center(title,146,24,(rgb[0]<<16)|(rgb[1]<<8)|rgb[2])
            else:
                mountains(.55,29)
                center('by',77,12,0x9FB6BF)
                center('Liuk_ITA',96,24,white)
                icecream()
                c.fillRect(0,234,45,6,0x009246)
                c.fillRect(45,234,45,6,0xFFFFFF)
                c.fillRect(90,234,45,6,0xCE2B37)
            if caption:center(caption,6,12,0xB9CFD9)
            c.push(0,0)
            remaining=40-ticks_diff(ticks_ms(),frame)
            if remaining>0:sleep_ms(remaining)
        if speaker is not None:speaker.stop()
        self.last_key=None

    def text(self,text,x,y,size=12,color=0xffffff,bg=0x1E2226):
        c=self.canvas
        c.setFont(getattr(self.fonts,'Montserrat%d'%size))
        c.setTextColor(color,bg)
        c.drawString(text,x,y)
    def digit(self,value,x,width,y,bg):
        self.canvas.setFont(self.fonts.Montserrat48)
        w=self.canvas.textWidth(value)
        self.text(value,x+(width-w)//2,y,48,bg=bg)
    def number(self,v,ready,bg):
        if ready:
            n=min(99,int(abs(v)*10+.5))
            sign='+' if v>=0 else '-'
            unit,decimal=str(n//10),str(n%10)
        else:sign,unit,decimal='-','-','-'
        self.digit(sign,1,32,29,bg)
        self.digit(unit,35,33,29,bg)
        self.text('.',69,29,48,bg=bg)  # absolute anchor, independent of sign/glyph widths
        self.digit(decimal,88,35,29,bg)
    def audio_icon(self,muted,ready,bg):
        c=self.canvas
        color=0xFF8A80 if muted else 0x70E6B2 if ready else 0x90979B
        c.fillRect(77,7,3,6,color)
        for a,b,d,e in ((80,7,85,3),(85,3,85,17),(85,17,80,13)):
            c.drawLine(a,b,d,e,color)
        if muted:
            c.drawLine(89,5,97,15,color);c.drawLine(97,5,89,15,color)
        else:
            c.drawLine(89,5,93,8,color);c.drawLine(93,8,93,12,color);c.drawLine(93,12,89,15,color)
    def draw(self,v,bar,p,tc,battery,profile,muted,connected,ready,overlay=False,warning=False,voltage=None,base_hz=None,volume=None,tuning=False,timbre=None,sound_overlay=False):
        v=max(-9.9,min(9.9,v))
        pos=164-int(max(-6.,min(6.,bar))*12.)
        tier=0 if abs(bar)<.20 else 1 if bar>0 else -1
        bg=0x0E3D1C if tier>0 else 0x3D1010 if tier<0 else 0x1E2226
        ptext='%.1f'%(p/100) if p else '----.-'
        ttext='%.1f'%tc if tc is not None else '--.-'
        btext='%.2fV'%voltage if voltage is not None else '--.--V'
        key=(round(v,1),v>=0,pos,bg,ptext,ttext,btext,profile,muted,connected,ready,overlay,warning,base_hz,volume,tuning,timbre,sound_overlay)
        if key==self.last_key:return False
        self.last_key=key
        c=self.canvas;c.fillScreen(bg)
        self.text(btext,4,3,12,0xE8EDF2,bg)
        if volume is not None:self.text(str(volume),50,3,12,0xE8EDF2,bg)
        self.audio_icon(muted,ready,bg)
        self.text('BLE',103,3,12,0x70E6B2 if connected else 0x90979B,bg)
        if tuning:
            self.text('%d Hz'%(base_hz or 0),4,32,24,bg=bg)
            self.text('VOL %d'%(volume or 0),4,63,14,bg=bg)
        elif overlay:
            # Large mnemonic replaces the numeric area briefly, not the bar.
            title=timbre.replace('_',' ') if sound_overlay and timbre else profile
            size=24
            c.setFont(getattr(self.fonts,'Montserrat%d'%size))
            if c.textWidth(title)>129:size=18
            self.text(title,4,38,size,bg=bg)
        else:self.number(v,ready,bg)
        if warning:self.text('FIFO !',72,76,12,0xFFAB91,bg)
        elif not ready:self.text('CAL 5s',72,76,12,0xE8EDF2,bg)
        c.fillRect(8,90,28,148,0x101010)
        c.drawRect(8,90,28,148,0x6E7A82)
        for value in range(-6,7):
            y=164-value*12
            c.drawLine(36,y,40 if value%3==0 else 38,y,0xE8EDF2)
        for label,value in (('+6',6),('+3',3),('0',0),('-3',-3),('-6',-6)):
            self.text(label,41,min(225,164-value*12-6),12,0x9AA6AE,bg)
        if pos<164:c.fillRect(11,pos,22,164-pos,0x12C43A)
        elif pos>164:c.fillRect(11,164,22,pos-164,0xC41A1A)
        c.drawLine(10,pos,33,pos,0xFFFFFF)
        c.drawLine(10,164,33,164,0x6E7A82)
        self.text('hPa',65,96,12,0x9AA6AE,bg)
        self.text(ptext,65,113,16,bg=bg)
        self.text('C',65,140,12,0x9AA6AE,bg)
        self.text(ttext,65,157,16,bg=bg)
        self.text(timbre.replace('FM_FERMA','FM FERMA') if timbre else '%dHz'%base_hz if base_hz else 'FILTRO',65,186,12,0x9AA6AE,bg)
        lines=('PASSA','BASSO') if profile=='PASSABASSO' else profile.split(' ',1)
        for i,line in enumerate(lines):self.text(line,65,204+i*18,14,bg=bg)
        c.push(0,0);self.frames+=1
        return True
    def error(self,message):
        c=self.canvas;c.fillScreen(0x201014)
        self.text('ERRORE',12,35,18,0xFF8A80,0x201014)
        for i in range(0,min(80,len(message)),17):self.text(message[i:i+17],3,80+(i//17)*19,12,bg=0x201014)
        c.push(0,0)

    def pairing(self,code,compare=True):
        key=('pairing',code,compare)
        if self.last_key==key:return
        self.last_key=key
        bg=0x152029
        self.canvas.fillScreen(bg)
        self.text('ABBINA BT',4,22,18,bg=bg)
        self.text('%06d'%code,5,75,24,0x75E8AA,bg)
        self.text('Confronta codici' if compare else 'Inserisci nel',3,120,12,bg=bg)
        self.text('A: conferma' if compare else 'telefono',3,143,14,bg=bg)
        self.text('B: annulla',3,177,14,bg=bg)
        self.canvas.push(0,0);self.frames+=1


# ---- main.py ----
"""UIFlow2 application entry point. Bundle build.py for RAM-only execution."""
import sys,time,gc
try: import select
except ImportError: import uselect as select
import M5
from hardware import Pin,I2C
import json,binascii

VERSION='vibevario-0.8.0'
PROJECT_NAME='VibeVario'
AUDIO_OUTPUT='speaker' # Change to speaker to restore the internal transducer.

class StickVarioApp:
    def __init__(self):
        M5.begin()
        self.old_gc_threshold=gc.threshold()
        gc.threshold(262144)
        M5.Lcd.powerSaveOff();M5.Lcd.setBrightness(180)
        self.screen=VarioDisplay(M5.Lcd)
        self.screen.splash(VERSION.rsplit('-',1)[-1],M5.update,time.sleep_ms,time.ticks_ms,time.ticks_diff,PROJECT_NAME,M5.Speaker)
        self.settings,config_error=load_config()
        if config_error:print('E,CONFIG_LOAD,%s'%config_error)
        self.timbre=self.settings['sounds'][0]
        self.control=ConfigProtocol(self.apply_config,self.preview_sound,self.settings)
        self.settings=self.control.config
        self.start_tick=self.previous_tick=time.ticks_ms()
        self.uptime=0
        self.bank=FilterBank()
        self.profile=FILTERS.index(self.settings['filters'][0])
        self.muted=False
        self.volume_target=160
        self.previous_volume=160
        self.usb_power=False
        self.tuning_until=0
        self.controls=TuningControls();self.pair_release=False
        self.raw=False
        self.lcd=True
        self.running=True
        self.last_poll=self.last_draw=self.last_telemetry=0
        self.last_stats=self.last_battery=0
        self.overlay_until=self.warning_until=0
        self.last_sample=-1000
        self.number=self.bar=0.
        self.visual_last=None
        self.pressure=self.temperature=None
        self.battery=None
        self.battery_voltage=None
        self.last_seq=None
        self.max_loop=self.max_draw=0
        self.i2c_errors=0
        self.costs={}
        self.trace=0
        self.audio=None
        self.link=None
        self.audio_output=None
        try:
            M5.Speaker.stop()
            self.audio_output=PWMPiezo(5) if AUDIO_OUTPUT=='piezo' else M5.Speaker
            self.audio=PCMAudio(self.audio_output,self.settings)
            self.audio.timbre=self.timbre;self.audio.base_hz=self.settings['base_hz']
            print('I,OUTPUT,%s,PCM_NATIVE_QUEUE' % AUDIO_OUTPUT)
        except Exception as e:print('E,AUDIO_INIT,%s'%e)
        try:
            import bluetooth
            self.link=BLELink(bluetooth,self.settings['remote_hid'])
        except Exception as e:
            print('E,BLE_INIT,%s'%e)
            if self.settings['remote_hid']:
                try:
                    self.link=BLELink(bluetooth,False)
                    print('I,HID_UNAVAILABLE,NUS_fallback')
                except Exception as e:print('E,BLE_FALLBACK,%s'%e)
        self.poller=select.poll()
        self.poller.register(sys.stdin,select.POLLIN)
        self.command_buffer=''
        self.cfg_buffer='';self.cfg_overflow=False;self.uart_drop=False
        self.sound_overlay=False
        self.sample_pause_ms=0
        self.config_tx=[];self.last_config_tx=0
        # Replace callbacks from the previous RAM app; poll debounced pressed state.
        for button in (M5.BtnA,M5.BtnB):
            button.setCallback(type=button.CB_TYPE.WAS_CLICKED,cb=self.ignore_button)
            button.setCallback(type=button.CB_TYPE.WAS_HOLD,cb=self.ignore_button)
        self.read_battery()
        # Start FIFO only after audio/BLE initialization to avoid startup backlog.
        try:
            self.sensor,self.sensor_info=discover_bmp581(I2C,Pin,M5.Power,time.sleep_ms)
        except Exception as e:
            self.screen.error(str(e))
            if self.audio:self.audio.stop()
            if self.link:self.link.close()
            gc.threshold(self.old_gc_threshold)
            raise
        self.external=GroveButtons(Pin,self.sensor_info,self.settings['grove_buttons'],M5.Power)
        print('I,KEYS,grove=%d,remote_hid=%d'%(self.external.pins is not None,bool(self.link and self.link.remote)))
        self.status_label=None
        print('I,BOOT,%s,BMP581_FIFO80_P16_T4_WM4'%VERSION)
        self.describe()
    def ignore_button(self,_):pass
    def now(self):
        tick=time.ticks_ms()
        self.uptime+=time.ticks_diff(tick,self.previous_tick)
        self.previous_tick=tick
        return self.uptime
    def read_battery(self):
        try:
            level=int(M5.Power.getBatteryLevel())
            self.battery=level if 0<=level<=100 else None
        except Exception:self.battery=None
        try:
            mv=M5.Power.getBatteryVoltage()
            self.battery_voltage=mv/1000. if 2500<=mv<=4500 else None
        except Exception:self.battery_voltage=None
        try:self.usb_power=M5.Power.getVBUSVoltage()>=4400
        except Exception:self.usb_power=False
        if self.audio:self.audio.set_volume(self.volume_target,self.usb_power)
    def event(self,source):
        name,key,sound=PROFILES[self.profile]
        print('P,%d,%d,%s,%s,%s,%s'%(self.now(),self.profile,name,key,sound,source))
    def next_profile(self,source='usb'):
        keys=self.settings['filters'];current=PROFILES[self.profile][1]
        self.profile=FILTERS.index(keys[(keys.index(current)+1)%len(keys)] if current in keys else keys[0])
        self.overlay_until=self.now()+1400
        self.sound_overlay=False
        self.visual_last=None
        if self.audio:self.audio.stop()
        self.event(source)
    def audio_event(self,source):
        self.tuning_until=self.now()+1800
        if self.audio:
            self.audio.preview(self.now())
            print('N,%d,base=%d,volume=%d,target=%d,usb=%d,source=%s'%(self.now(),self.audio.base_hz,self.audio.master_volume,self.volume_target,self.usb_power,source))
    def apply_config(self,config):
        self.settings=config
        if hasattr(self,'sensor_info'):
            enabled=config['grove_buttons'] and self.sensor_info['bus']=='HEADER'
            if enabled!=(self.external.pins is not None):
                self.external=GroveButtons(Pin,self.sensor_info,enabled,M5.Power)
        if PROFILES[self.profile][1] not in config['filters']:self.profile=FILTERS.index(config['filters'][0])
        if self.timbre not in config['sounds']:self.timbre=config['sounds'][0]
        if self.audio:
            self.audio.stop();self.audio.settings=config;self.audio.timbre=self.timbre;self.audio.base_hz=config['base_hz']
        self.visual_last=None;self.overlay_until=self.now()+1400
        self.event('config')
    def preview_sound(self,sound):
        if self.audio:
            # Preview is temporary; restore selected timbre on the next normal update.
            self.audio.timbre=sound;self.audio.preview(self.now());self.audio.timbre=self.timbre
    def next_note(self,source='hold_a'):
        self.status_label=None
        keys=self.settings['sounds'];self.timbre=keys[(keys.index(self.timbre)+1)%len(keys)]
        if self.audio:self.audio.timbre=self.timbre
        self.overlay_until=self.now()+1400;self.tuning_until=0;self.sound_overlay=True
        self.audio_event(source);self.tuning_until=0
    def config_request(self,line,ble=False):
        try:
            request=json.loads(line)
            pausing=isinstance(request,dict) and request.get('op')=='save' and request.get('v')==1 and type(request.get('id'))==int and not self.control.saved
            if pausing:
                start=self.now()
                if self.audio:self.audio.stop()
                self.sensor.write(0x37,0x30);time.sleep_ms(12)
                self.acquire(self.now(),True)
                print('I,ACQ_PAUSE_BEGIN,save,seq=%d'%self.sensor.seq)
                try:reply=self.control.handle(request)
                finally:
                    self.sensor.write(0x37,0x31)
                    gap=self.now()-start;self.sample_pause_ms+=gap
                    if self.sensor.first_ms is not None:self.sensor.first_ms+=gap
                    self.bank.restart();self.visual_last=None
                    print('I,ACQ_RESUME,save,gap_ms=%d,seq=%d,timing_uncertain'%(gap,self.sensor.seq))
            else:reply=self.control.handle(request)
        except Exception as e:reply={'v':1,'id':None,'ok':False,'error':str(e)[:100]}
        reply['firmware']=VERSION
        reply['hardware']=dict(self.sensor_info,grove_buttons=self.external.pins is not None,remote_hid=bool(self.link and self.link.remote),restart_required=bool(self.link and bool(self.link.remote)!=self.settings['remote_hid']))
        if self.link:
            name=self.link.ble.config('gap_name')
            reply['hardware']['ble_name']=name.decode() if isinstance(name,bytes) else str(name)
        if self.link and self.link.remote:
            h=self.link.remote
            reply['bond_store']={'get_calls':h.secret_gets,'set_calls':h.secret_sets,'entries':len(h.secrets),'dirty':h.dirty}
        reply['ble_security']=self.link.remote.security if self.link and self.link.remote else None
        reply['active']={'filter':PROFILES[self.profile][1],'sound':self.timbre,'volume':self.audio.master_volume if self.audio else 0,'base_hz':self.settings['base_hz'],'pattern':self.settings['pattern']}
        encoded=json.dumps(reply)
        if ble and self.link:self.link.config_reply(encoded)
        else:
            data=binascii.b2a_base64(encoded.encode()).decode().strip()
            chunks=[data[i:i+64] for i in range(0,len(data),64)]
            ident=reply.get('id');ident=ident if type(ident)==int else -1
            self.config_tx=['@CF1 %d:%d:%d:%s'%(ident,i,len(chunks),piece) for i,piece in enumerate(chunks)]
    def set_volume(self,value,source):
        self.volume_target=max(0,min(255,int(value)))
        if self.volume_target:self.previous_volume=self.volume_target
        self.muted=self.volume_target==0
        if self.audio:self.audio.set_volume(self.volume_target,self.usb_power)
        self.audio_event(source)
    def next_volume(self):
        levels=[v for v in self.settings['volumes'] if self.usb_power or v<=190]
        i=levels.index(self.volume_target) if self.volume_target in levels else len(levels)-1
        self.set_volume(levels[(i+1)%len(levels)],'button_b')
    def next_frequency(self):
        notes=self.settings['base_notes'];current=self.settings['base_hz']
        value=notes[(notes.index(current)+1)%len(notes)] if current in notes else notes[0]
        self.settings['base_hz']=value;self.control.saved=False
        if self.audio:self.audio.stop();self.audio.base_hz=value
        self.tuning_until=self.now()+1400;self.audio_event('grove_frequency')
        # audio_event also starts the tuning overlay.
    def next_pattern(self):
        patterns=self.settings['patterns'];current=self.settings['pattern']
        value=patterns[(patterns.index(current)+1)%len(patterns)] if current in patterns else patterns[0]
        self.settings['pattern']=value;self.control.saved=False
        if self.audio:self.audio.stop()
        self.status_label={'classic':'BIP CLASSICO','continuous':'CONTINUO','dualmean':'DOPPIA MEDIA','curves':'CURVA','pair':'DOPPIO TONO'}[value]
        self.overlay_until=self.now()+1400;self.tuning_until=0;self.sound_overlay=True
        print('I,PATTERN,%d,%s'%(self.now(),value))
    def remote_page(self):
        sent=bool(self.link and self.link.remote_page())
        print('I,REMOTE_PAGE,%d,queued=%d'%(self.now(),sent))
    def buttons(self,now):
        remote=self.link.remote if self.link else None
        if remote and remote.pairing_buttons(now,M5.BtnA.isPressed(),M5.BtnB.isPressed()):
            self.controls=TuningControls();self.pair_release=True
            return
        if self.pair_release:
            if not M5.BtnA.isPressed() and not M5.BtnB.isPressed():self.pair_release=False
            return
        for action in self.controls.update(now,M5.BtnA.isPressed(),M5.BtnB.isPressed()):
            if action=='note':self.next_note()
            elif action=='profile':self.next_profile('button_a')
            elif action=='volume':self.next_volume()
            elif action=='zero':self.zero('button_b_hold')
        for action in self.external.update(now):
            if action=='frequency':self.next_frequency()
            elif action=='pattern':self.next_pattern()
            elif action=='page':self.remote_page()
    def save_bonds(self):
        start=self.now()
        if self.audio:self.audio.stop()
        self.sensor.write(0x37,0x30);time.sleep_ms(12);self.acquire(self.now(),True)
        print('I,ACQ_PAUSE_BEGIN,ble_bond,seq=%d'%self.sensor.seq)
        try:self.link.remote.save()
        except Exception as e:
            self.link.remote.dirty=False;print('E,BLE_BOND_SAVE,%s'%e)
        finally:
            self.sensor.write(0x37,0x31);gap=self.now()-start;self.sample_pause_ms+=gap
            if self.sensor.first_ms is not None:self.sensor.first_ms+=gap
            self.bank.restart();self.visual_last=None
            print('I,ACQ_RESUME,ble_bond,gap_ms=%d,seq=%d,timing_uncertain'%(gap,self.sensor.seq))
    def zero(self,source):
        self.bank.zero()
        self.visual_last=None
        if self.audio:self.audio.stop()
        print('I,ZERO,%d,%s'%(self.now(),source))
    def describe(self):
        print('C,16,4,80,FIFO,OK')
        print('I,REG,'+','.join('%02X=%02X'%(k,v) for k,v in self.sensor.readback.items()))
        self.stats()
        if self.audio:print('I,AUDIO,base=%d,volume=%d,target=%d,channel=255,usb=%d'%(self.audio.base_hz,self.audio.master_volume,self.volume_target,self.usb_power))
        print('I,READY,ble=%d,audio=%d,profile=%s,raw=%d'%(self.link is not None,self.audio is not None,PROFILES[self.profile][0],self.raw))
    def stats(self):
        print('I,STAT,seq=%d,max_fifo=%d,near_full=%d,invalid=%d,i2c_err=%d,loop_max_ms=%d,draw_max_ms=%d,frames=%d,ble=%d,tx=%d,audio_err=%d,mem=%d'%(
            self.sensor.seq,self.sensor.max_fifo,self.sensor.near_full,self.sensor.invalid,
            self.i2c_errors,self.max_loop,self.max_draw,self.screen.frames,
            len(self.link.connections) if self.link else 0,self.link.messages if self.link else 0,
            self.audio.errors if self.audio else -1,gc.mem_free()))
        if self.audio:print('I,PCM,calls=%d,render_max_us=%d,queued=%d,underruns=%d,update_gap=%d,stream=%d'%(self.audio.calls,self.audio.max_render_us,int(M5.Speaker.isPlaying(0)),self.audio.underruns,self.audio.update_gap,self.audio.loop_key is not None))
        print('I,COST,'+','.join('%s=%d'%item for item in self.costs.items()))
    def command(self,line):
        if line.startswith('@CFG '):self.config_request(line[5:]);return
        args=line.upper().split()
        if not args:return
        try:
            cmd=args[0]
            if cmd in ('GET','DIAG'):self.describe()
            elif cmd=='RAW':self.raw=bool(int(args[1]));print('I,RAW,%d'%self.raw)
            elif cmd=='LCD':self.lcd=bool(int(args[1]));self.screen.last_key=None;print('I,LCD,%d'%self.lcd)
            elif cmd=='MUTE':
                mute=bool(int(args[1])) if len(args)>1 else not self.muted
                self.set_volume(0 if mute else self.previous_volume,'usb_mute')
            elif cmd=='VOL':self.set_volume(int(args[1]),'usb_volume')
            elif cmd=='NOTE':self.next_note('usb_note')
            elif cmd=='BASE':
                value=int(args[1])
                if value not in BASE_NOTES:raise ValueError('base note')
                if self.audio:self.audio.base_hz=value;self.settings['base_hz']=value;self.control.saved=False;self.audio_event('usb_base')
            elif cmd=='NEXT':self.next_profile()
            elif cmd=='PROFILE':
                target=int(args[1])
                if not 0<=target<len(PROFILES):raise ValueError('profile0..7')
                self.profile=target;self.overlay_until=self.now()+1400;self.visual_last=None
                if self.audio:self.audio.stop()
                self.event('usb')
            elif cmd=='ZERO':self.zero('usb')
            elif cmd=='STOP':self.running=False
            else:print('E,CMD,%s'%cmd)
        except Exception as e:print('E,CMD,%s'%e)
    def receive_commands(self):
        for _ in range(64):
            if not self.poller.poll(0):break
            ch=sys.stdin.read(1)
            if ch in ('\r','\n'):
                if self.command_buffer and not self.uart_drop:self.command(self.command_buffer)
                self.command_buffer='';self.uart_drop=False
            elif ch and 32<=ord(ch)<=126:
                if not self.uart_drop and len(self.command_buffer)<2048:self.command_buffer+=ch
                else:self.command_buffer='';self.uart_drop=True
        if self.link and self.link.cfg_rx:
            self.cfg_buffer+=self.link.cfg_rx.decode('utf-8','replace');self.link.cfg_rx=b''
            if len(self.cfg_buffer)>2048:self.cfg_buffer='';print('E,CFG_OVERFLOW')
        if '\n' in self.cfg_buffer:
            line,self.cfg_buffer=self.cfg_buffer.split('\n',1);self.config_request(line.strip(),True)
        if self.link and self.link.rx_pending:
            data=self.link.rx_pending;self.link.rx_pending=b''
            try:self.command(data.decode().strip())
            except Exception:print('E,BLE_COMMAND')
    def acquire(self,now,force=False):
        try:block=self.sensor.poll(now,force)
        except Exception as e:
            self.i2c_errors+=1
            if self.i2c_errors<4:print('E,I2C,%s'%e)
            if self.audio:self.audio.stop()
            return
        if block is None:return
        first,n,anchor,samples=block
        if self.raw:print('F,%d,%d,%d'%(first,n,anchor))
        if n>=15:
            self.warning_until=now+3000
            self.bank.restart()
            self.visual_last=None
            print('E,FIFO_NEAR_FULL,%d,timing_uncertain'%n)
        for seq,nominal,batch,p,tc in samples:
            if self.last_seq is not None and seq!=self.last_seq+1:
                self.bank.restart();self.warning_until=now+3000
                print('E,SAMPLE_GAP,%d,%d'%(self.last_seq,seq))
            self.last_seq=seq
            self.pressure,self.temperature=p,tc
            self.last_sample=now
            t=(seq-1)/80.+self.sample_pause_ms/1000.
            self.bank.update(t,p,tc)
            v=self.bank.values[PROFILES[self.profile][1]]
            if v is not None:
                if self.visual_last is None:self.number=self.bar=v
                else:
                    dt=t-self.visual_last
                    self.number+=alpha(dt,.65)*(v-self.number)
                    self.bar+=alpha(dt,.25)*(v-self.bar)
                self.visual_last=t
            if self.raw:print('S,%d,%d,%.4f,%.4f,16,4,80,FIFO'%(seq,round(nominal),p,tc))
    def stage(self,name,last):
        now=self.now()
        self.costs[name]=max(self.costs.get(name,0),now-last)
        return now
    def loop(self):
        begin=self.now()
        M5.update()
        self.buttons(self.now())
        stage=self.stage('m5',begin)
        self.receive_commands()
        stage=self.stage('cmd',stage)
        now=self.now()
        # Drain acquisition before graphics/telemetry, not at display refresh rate.
        if now-self.last_poll>=8:self.last_poll=now;self.acquire(now)
        stage=self.stage('acq',stage)
        now=self.now()
        name,key,kind=PROFILES[self.profile]
        kind=self.settings['pattern']
        v=self.bank.values[key]
        valid=self.bank.ready and v is not None and now-self.last_sample<300 and now>=self.warning_until
        if self.audio:self.audio.update(now,v,self.bank.slow[key],kind,valid and not self.muted)
        stage=self.stage('audio',stage)
        now=self.now()
        if now-self.last_poll>=8:self.last_poll=now;self.acquire(now)
        if self.config_tx and now-self.last_config_tx>=20:
            print(self.config_tx.pop(0));self.last_config_tx=now
        if self.link:
            self.link.pump()
            if self.link.remote:
                self.link.remote.pump(now)
                while self.link.remote.events:
                    print('I,BLE_SEC,'+','.join(str(x) for x in self.link.remote.events.pop(0)))
                if self.link.remote.dirty:self.save_bonds();valid=False
            if valid and now-self.last_telemetry>=100:
                self.last_telemetry=now
                self.link.publish(now,self.pressure,self.temperature,v,self.battery)
        stage=self.stage('ble',stage)
        if now-self.last_battery>=2000:self.last_battery=now;self.read_battery()
        stage=self.stage('power',stage)
        if self.lcd and now-self.last_draw>=100:
            self.last_draw=now
            draw_start=self.now()
            if self.link and self.link.remote and self.link.remote.pairing:
                self.screen.pairing(self.link.remote.pairing[2],self.link.remote.pairing[1]==4)
            else:self.screen.draw(self.number,self.bar,self.pressure,self.temperature,self.battery,name,
                             self.muted,bool(self.link and self.link.connections),valid,
                             now<self.overlay_until,now<self.warning_until,voltage=self.battery_voltage,
                             base_hz=self.audio.base_hz if self.audio else None,volume=self.audio.master_volume if self.audio else 0,
                             tuning=now<self.tuning_until,timbre=self.status_label or self.timbre.upper(),sound_overlay=self.sound_overlay)
            self.max_draw=max(self.max_draw,self.now()-draw_start)
        stage=self.stage('draw',stage)
        now=self.now()
        if now-self.last_poll>=8:self.last_poll=now;self.acquire(now)
        if now-self.last_stats>=5000:self.last_stats=now;self.stats()
        stage=self.stage('stat',stage)
        self.max_loop=max(self.max_loop,self.now()-begin)
        time.sleep_ms(1)
    def run(self):
        try:
            while self.running:self.loop()
        finally:
            if self.audio:self.audio.stop()
            if self.audio_output and hasattr(self.audio_output,'close'):self.audio_output.close()
            if self.link:self.link.close()
            gc.threshold(self.old_gc_threshold)
            print('I,STOPPED')

if __name__=='__main__':
    app=None
    try:
        app=StickVarioApp()
        app.run()
    except KeyboardInterrupt:pass
    except Exception as e:
        print('E,FATAL,%s'%e)
        try:M5.Speaker.stop()
        except Exception:pass
        if app:
            try:
                if app.audio_output and hasattr(app.audio_output,'close'):app.audio_output.close()
            except Exception:pass
            try:app.screen.error(str(e))
            except Exception:pass
        raise

