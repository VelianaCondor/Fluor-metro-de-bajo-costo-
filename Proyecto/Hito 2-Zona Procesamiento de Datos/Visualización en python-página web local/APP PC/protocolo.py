"""
protocolo.py — Tramas entre el ESP32-S3 maestro y la PC (idénticas por USB/COM y por Wi-Fi/TCP).

  | A5 5A | tipo u8 | seq u8 | len u32 LE | payload (len bytes) | crc16 u16 LE |
  CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF) calculado sobre tipo..payload.
  binascii.crc_hqx(datos, 0xFFFF) implementa exactamente ese CRC.
"""
from __future__ import annotations

import binascii
import json
import struct
from dataclasses import dataclass

SYNC = b"\xA5\x5A"

T_HELLO, T_LOG = 0x01, 0x03
T_PD, T_TERM, T_OJIP, T_IMG, T_ESTADO, T_INT = 0x10, 0x11, 0x12, 0x13, 0x14, 0x15
T_CMD, T_RESP = 0x80, 0x81

NOMBRES = {T_HELLO: "hello", T_LOG: "log", T_PD: "pd", T_TERM: "term", T_OJIP: "ojip",
           T_IMG: "img", T_ESTADO: "estado", T_INT: "int", T_CMD: "cmd", T_RESP: "resp"}

# Cabeceras binarias (deben coincidir con los struct packed del firmware)
CAB_OJIP = struct.Struct("<HHIIfffBBff")   # id, n_bins, n_muestras, dur_ms, fs_hz, v_dark, ruido, sat, led, T1, T2
BIN_OJIP = struct.Struct("<ffH")           # t_s, v (V, sin offset), n (muestras en el bin)
CAB_INT = struct.Struct("<HHHIIffffBBff")  # id, captura_id, n, dur_ms, t_foto_ms, v_dark, ruido, v_foto, sd_foto, foto, sat, T1, T2
PT_INT = struct.Struct("<ff")              # t_s (desde que se enciende el LED), v (V, sin línea base)
CAB_IMG = struct.Struct("<HHBHHBIII")      # foto_id, captura_id, rol, ancho, alto, formato, crc32, bytes, t_rx_ms

FORMATOS_IMG = {1: "RGB565", 2: "GRAY8", 3: "JPEG"}
ROLES = {0: "oscuro", 1: "luz"}


def crc16(datos: bytes, crc: int = 0xFFFF) -> int:
    return binascii.crc_hqx(datos, crc)


def codificar(tipo: int, payload: bytes, seq: int = 0) -> bytes:
    cab = struct.pack("<BBI", tipo, seq & 0xFF, len(payload))
    return SYNC + cab + payload + struct.pack("<H", crc16(cab + payload))


def comando(cmd: str, **kw) -> bytes:
    """Trama de comando PC -> S3, p. ej. comando('ojip', dur_ms=1000, laser=1)."""
    return codificar(T_CMD, json.dumps({"cmd": cmd, **kw}, separators=(",", ":")).encode())


@dataclass
class Trama:
    tipo: int
    seq: int
    payload: bytes

    @property
    def nombre(self) -> str:
        return NOMBRES.get(self.tipo, f"0x{self.tipo:02X}")


class Decodificador:
    """Máquina de estados tolerante a basura: busca A5 5A, valida longitud y CRC, y se resincroniza."""

    MAX_LEN = 1_000_000

    def __init__(self) -> None:
        self.buf = bytearray()
        self.errores_crc = 0
        self.bytes_basura = 0
        self.tramas_ok = 0

    def alimentar(self, datos: bytes) -> list[Trama]:
        self.buf += datos
        out: list[Trama] = []
        while True:
            i = self.buf.find(SYNC)
            if i < 0:                                   # conserva un posible 0xA5 al final
                keep = 1 if self.buf[-1:] == b"\xA5" else 0
                self.bytes_basura += len(self.buf) - keep
                del self.buf[: len(self.buf) - keep]
                break
            if i:
                self.bytes_basura += i
                del self.buf[:i]
            if len(self.buf) < 8:
                break
            tipo, seq, n = struct.unpack_from("<BBI", self.buf, 2)
            if n > self.MAX_LEN:
                del self.buf[:2]
                continue
            total = 8 + n + 2
            if len(self.buf) < total:
                break
            cab, pl = bytes(self.buf[2:8]), bytes(self.buf[8:8 + n])
            (crc,) = struct.unpack_from("<H", self.buf, 8 + n)
            if crc16(cab + pl) == crc:
                out.append(Trama(tipo, seq, pl))
                self.tramas_ok += 1
                del self.buf[:total]
            else:
                self.errores_crc += 1
                del self.buf[:2]
        return out


def interpretar(tr: Trama) -> dict:
    """Convierte una trama en un diccionario de Python listo para procesar."""
    if tr.tipo in (T_HELLO, T_PD, T_TERM, T_ESTADO, T_RESP):
        d = json.loads(tr.payload.decode("utf-8", "replace"))
        d["_tipo"] = tr.nombre
        return d
    if tr.tipo == T_LOG:
        return {"_tipo": "log", "texto": tr.payload.decode("utf-8", "replace")}
    if tr.tipo == T_OJIP:
        c = CAB_OJIP.unpack_from(tr.payload, 0)
        cab = dict(zip(("id", "n_bins", "n_muestras", "dur_ms", "fs_hz", "v_dark", "ruido_dark",
                        "sat", "led", "T1", "T2"), c))
        t, v, n = [], [], []
        off = CAB_OJIP.size
        for _ in range(cab["n_bins"]):
            ti, vi, ni = BIN_OJIP.unpack_from(tr.payload, off)
            off += BIN_OJIP.size
            t.append(ti); v.append(vi); n.append(ni)
        return {"_tipo": "ojip", **cab, "t": t, "v": v, "n": n}
    if tr.tipo == T_INT:
        c = CAB_INT.unpack_from(tr.payload, 0)
        cab = dict(zip(("id", "captura_id", "n", "dur_ms", "t_foto_ms", "v_dark", "ruido_dark", "v_foto",
                        "sd_foto", "foto", "sat", "T1", "T2"), c))
        t, v = [], []
        for k in range(cab["n"]):
            ti, vi = PT_INT.unpack_from(tr.payload, CAB_INT.size + k * PT_INT.size)
            t.append(ti); v.append(vi)
        return {"_tipo": "int", **cab, "t": t, "v": v}
    if tr.tipo == T_IMG:
        c = CAB_IMG.unpack_from(tr.payload, 0)
        cab = dict(zip(("foto_id", "captura_id", "rol", "ancho", "alto", "formato", "crc32", "bytes", "t_rx_ms"), c))
        datos = tr.payload[CAB_IMG.size:CAB_IMG.size + cab["bytes"]]
        return {"_tipo": "img", **cab, "formato_txt": FORMATOS_IMG.get(cab["formato"], "?"),
                "rol_txt": ROLES.get(cab["rol"], "?"), "datos": datos}
    return {"_tipo": tr.nombre, "raw": tr.payload.hex()}
