"""최소 Modbus TCP 슬레이브 구현 (외부 의존성 없음).

pymodbus 3.15 에서 datastore API 가 폐기되어 버전 종속이 생겼다.
Modbus TCP 는 MBAP 헤더 + PDU 로 단순하므로 필요한 기능코드만 직접 구현한다.

지원 기능코드
    FC 01  Read Coils
    FC 02  Read Discrete Inputs
    FC 03  Read Holding Registers
    FC 04  Read Input Registers
    FC 05  Write Single Coil
    FC 06  Write Single Register
    FC 15  Write Multiple Coils
    FC 16  Write Multiple Registers

프레임 구조 (MODBUS Application Protocol Specification V1.1b3)
    MBAP: 트랜잭션ID(2) 프로토콜ID(2, =0) 길이(2) 유닛ID(1)   — 전부 빅엔디안
    PDU : 기능코드(1) 데이터(...)
    예외응답: (기능코드 | 0x80) 예외코드(1)
"""
from __future__ import annotations

import socket
import socketserver
import struct
import threading

# 예외 코드 (사양 §7)
EX_ILLEGAL_FUNCTION = 0x01
EX_ILLEGAL_ADDRESS = 0x02
EX_ILLEGAL_VALUE = 0x03

MAX_READ_BITS = 2000
MAX_READ_REGS = 125
MAX_WRITE_REGS = 123


class DataStore:
    """코일·이산입력·홀딩레지스터·입력레지스터 저장소 (스레드 안전).

    주소는 0 기반(zero-based)이다. 문서상 표기 IR 0 은 프로토콜 주소 0 에 대응한다.
    """

    def __init__(self, n_co: int = 64, n_di: int = 64, n_hr: int = 64, n_ir: int = 64) -> None:
        self.co = [False] * n_co
        self.di = [False] * n_di
        self.hr = [0] * n_hr
        self.ir = [0] * n_ir
        self.lock = threading.RLock()

    # ---- 편의 접근자 (브리지에서 사용)
    def get_hr(self, addr: int, n: int) -> list[int]:
        with self.lock:
            return self.hr[addr:addr + n]

    def set_hr(self, addr: int, vals: list[int]) -> None:
        with self.lock:
            self.hr[addr:addr + len(vals)] = [v & 0xFFFF for v in vals]

    def get_co(self, addr: int, n: int) -> list[bool]:
        with self.lock:
            return self.co[addr:addr + n]

    def set_co(self, addr: int, vals: list[bool]) -> None:
        with self.lock:
            self.co[addr:addr + len(vals)] = [bool(v) for v in vals]

    def set_ir(self, addr: int, vals: list[int]) -> None:
        with self.lock:
            self.ir[addr:addr + len(vals)] = [v & 0xFFFF for v in vals]

    def set_di(self, addr: int, vals: list[bool]) -> None:
        with self.lock:
            self.di[addr:addr + len(vals)] = [bool(v) for v in vals]


def _pack_bits(bits: list[bool]) -> bytes:
    """비트 목록을 Modbus 바이트 배열로 포장한다 (LSB 먼저)."""
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def _unpack_bits(data: bytes, count: int) -> list[bool]:
    """Modbus 바이트 배열에서 비트 count 개를 푼다."""
    return [bool(data[i // 8] & (1 << (i % 8))) for i in range(count)]


def handle_pdu(store: DataStore, pdu: bytes) -> bytes:
    """PDU 하나를 처리해 응답 PDU 를 만든다.

    Args:
        store: 데이터 저장소
        pdu: 기능코드로 시작하는 요청 PDU

    Returns:
        응답 PDU (예외응답 포함)
    """
    if not pdu:
        return bytes([0x80, EX_ILLEGAL_FUNCTION])
    fc = pdu[0]

    def err(code: int) -> bytes:
        return bytes([fc | 0x80, code])

    try:
        if fc in (1, 2, 3, 4):
            addr, qty = struct.unpack(">HH", pdu[1:5])
            src, is_bits = ({1: (store.co, True), 2: (store.di, True),
                             3: (store.hr, False), 4: (store.ir, False)})[fc]
            lim = MAX_READ_BITS if is_bits else MAX_READ_REGS
            if qty < 1 or qty > lim:
                return err(EX_ILLEGAL_VALUE)
            with store.lock:
                if addr + qty > len(src):
                    return err(EX_ILLEGAL_ADDRESS)
                vals = src[addr:addr + qty]
            if is_bits:
                body = _pack_bits(vals)
                return bytes([fc, len(body)]) + body
            body = b"".join(struct.pack(">H", v & 0xFFFF) for v in vals)
            return bytes([fc, len(body)]) + body

        if fc == 5:                                       # Write Single Coil
            addr, val = struct.unpack(">HH", pdu[1:5])
            if val not in (0x0000, 0xFF00):
                return err(EX_ILLEGAL_VALUE)
            with store.lock:
                if addr >= len(store.co):
                    return err(EX_ILLEGAL_ADDRESS)
                store.co[addr] = (val == 0xFF00)
            return pdu[:5]                                # 요청 에코

        if fc == 6:                                       # Write Single Register
            addr, val = struct.unpack(">HH", pdu[1:5])
            with store.lock:
                if addr >= len(store.hr):
                    return err(EX_ILLEGAL_ADDRESS)
                store.hr[addr] = val & 0xFFFF
            return pdu[:5]

        if fc == 15:                                      # Write Multiple Coils
            addr, qty, nbytes = struct.unpack(">HHB", pdu[1:6])
            bits = _unpack_bits(pdu[6:6 + nbytes], qty)
            with store.lock:
                if addr + qty > len(store.co):
                    return err(EX_ILLEGAL_ADDRESS)
                store.co[addr:addr + qty] = bits
            return struct.pack(">BHH", fc, addr, qty)

        if fc == 16:                                      # Write Multiple Registers
            addr, qty, nbytes = struct.unpack(">HHB", pdu[1:6])
            if qty < 1 or qty > MAX_WRITE_REGS or nbytes != qty * 2:
                return err(EX_ILLEGAL_VALUE)
            vals = list(struct.unpack(">" + "H" * qty, pdu[6:6 + nbytes]))
            with store.lock:
                if addr + qty > len(store.hr):
                    return err(EX_ILLEGAL_ADDRESS)
                store.hr[addr:addr + qty] = vals
            return struct.pack(">BHH", fc, addr, qty)

        return err(EX_ILLEGAL_FUNCTION)
    except (struct.error, IndexError, KeyError):
        return err(EX_ILLEGAL_VALUE)


class _Handler(socketserver.BaseRequestHandler):
    """MBAP 프레이밍 처리. 연결 하나당 스레드 하나."""

    def handle(self) -> None:
        self.request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        buf = b""
        while True:
            try:
                chunk = self.request.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while len(buf) >= 7:
                tid, pid, length, unit = struct.unpack(">HHHB", buf[:7])
                if pid != 0:                              # Modbus 프로토콜이 아니면 끊는다
                    return
                total = 6 + length
                if len(buf) < total:
                    break
                pdu = buf[7:total]
                buf = buf[total:]
                resp = handle_pdu(self.server.store, pdu)
                head = struct.pack(">HHHB", tid, 0, len(resp) + 1, unit)
                try:
                    self.request.sendall(head + resp)
                except OSError:
                    return


class ModbusTcpServer(socketserver.ThreadingTCPServer):
    """스레딩 Modbus TCP 슬레이브."""

    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], store: DataStore) -> None:
        self.store = store
        super().__init__(address, _Handler)


def serve(host: str, port: int, store: DataStore) -> ModbusTcpServer:
    """서버를 만들어 별도 스레드에서 돌린다.

    Args:
        host: 바인드 주소
        port: 포트
        store: 데이터 저장소

    Returns:
        ModbusTcpServer (shutdown() 으로 정지)
    """
    srv = ModbusTcpServer((host, port), store)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ---------------------------------------------------------------- 최소 클라이언트 (시험용)


class ModbusTcpClient:
    """시험·검증용 최소 Modbus TCP 마스터."""

    def __init__(self, host: str, port: int, unit: int = 1, timeout: float = 3.0) -> None:
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.unit, self.tid = unit, 0

    def _tx(self, pdu: bytes) -> bytes:
        self.tid = (self.tid + 1) & 0xFFFF
        self.sock.sendall(struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit) + pdu)
        head = self._recv_exact(7)
        length = struct.unpack(">H", head[4:6])[0]
        body = self._recv_exact(length - 1)
        if body[0] & 0x80:
            raise RuntimeError(f"Modbus 예외 fc=0x{body[0]:02x} code={body[1]}")
        return body

    def _recv_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            c = self.sock.recv(n - len(out))
            if not c:
                raise ConnectionError("연결이 끊겼다")
            out += c
        return out

    def read_input_registers(self, addr: int, count: int) -> list[int]:
        b = self._tx(struct.pack(">BHH", 4, addr, count))
        return list(struct.unpack(">" + "H" * count, b[2:2 + count * 2]))

    def read_holding_registers(self, addr: int, count: int) -> list[int]:
        b = self._tx(struct.pack(">BHH", 3, addr, count))
        return list(struct.unpack(">" + "H" * count, b[2:2 + count * 2]))

    def read_discrete_inputs(self, addr: int, count: int) -> list[bool]:
        b = self._tx(struct.pack(">BHH", 2, addr, count))
        return _unpack_bits(b[2:2 + b[1]], count)

    def read_coils(self, addr: int, count: int) -> list[bool]:
        b = self._tx(struct.pack(">BHH", 1, addr, count))
        return _unpack_bits(b[2:2 + b[1]], count)

    def write_register(self, addr: int, value: int) -> None:
        self._tx(struct.pack(">BHH", 6, addr, value & 0xFFFF))

    def write_coil(self, addr: int, value: bool) -> None:
        self._tx(struct.pack(">BHH", 5, addr, 0xFF00 if value else 0x0000))

    def write_registers(self, addr: int, values: list[int]) -> None:
        n = len(values)
        self._tx(struct.pack(">BHHB", 16, addr, n, n * 2)
                 + b"".join(struct.pack(">H", v & 0xFFFF) for v in values))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
