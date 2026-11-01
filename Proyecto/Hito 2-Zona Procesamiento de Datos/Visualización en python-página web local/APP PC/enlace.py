"""
enlace.py — Conexión PC <-> ESP32-S3 por puerto COM (pyserial) o Wi-Fi (TCP), con decisión automática.

Modo "auto":
  1. Busca puertos serie con VID de puentes USB conocidos (WCH CH34x, Espressif nativo, Silabs CP210x).
  2. Abre cada uno, envía HELLO y espera la respuesta HELLO del S3 (1.5 s).
  3. Si ninguno responde, escucha 2.5 s el anuncio UDP del S3 (puerto 3334) para conocer su IP
     —sirve tanto con el router del laboratorio como con la red propia del S3— y prueba TCP con
     esas IP y con las de la lista (por defecto 192.168.4.1:3333).
  4. Una vez conectado envía un latido ("hb") cada 1 s. Si no llega ninguna trama en 5 s,
     el enlace se declara caído y se vuelve al paso 1.
El S3 aplica la misma regla por su lado: transmite por el enlace del que recibió la última trama.
"""
from __future__ import annotations

import socket
import threading
import time
from typing import Callable

from protocolo import Decodificador, Trama, T_HELLO, comando

try:
    import serial
    from serial.tools import list_ports
except ImportError:                       # permite usar solo Wi-Fi sin pyserial
    serial = None
    list_ports = None

VIDS_CONOCIDOS = {0x1A86: "WCH CH34x", 0x303A: "Espressif USB nativo", 0x10C4: "Silabs CP210x"}
PUERTO_ANUNCIO = 3334


def descubrir(espera_s: float = 2.5) -> list[str]:
    """IP anunciadas por el S3 por broadcast UDP: {"dev":"fluorometro-s3","ip":...,"tcp":3333}."""
    import json
    ips: list[str] = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", PUERTO_ANUNCIO))
        s.settimeout(0.3)
        fin = time.time() + espera_s
        while time.time() < fin:
            try:
                d, _ = s.recvfrom(512)
                j = json.loads(d)
                if j.get("dev") == "fluorometro-s3" and j.get("ip") not in ips:
                    ips.append(j["ip"])
            except (socket.timeout, ValueError):
                pass
    except OSError:
        pass
    finally:
        s.close()
    return ips


class Transporte:
    nombre = "?"

    def leer(self) -> bytes: ...
    def escribir(self, datos: bytes) -> None: ...
    def cerrar(self) -> None: ...


class TransporteSerie(Transporte):
    def __init__(self, puerto: str, baud: int = 921600):
        self.ser = serial.Serial(puerto, baud, timeout=0.05)
        try:                              # evita reiniciar el ESP32 al abrir el puerto (placas con auto-reset)
            self.ser.dtr = False
            self.ser.rts = False
        except (OSError, serial.SerialException):
            pass                          # puertos virtuales (simulador) no tienen líneas de control
        self.nombre = f"usb:{puerto}"

    def leer(self) -> bytes:
        return self.ser.read(self.ser.in_waiting or 1)

    def escribir(self, datos: bytes) -> None:
        self.ser.write(datos)

    def cerrar(self) -> None:
        self.ser.close()


class TransporteTCP(Transporte):
    def __init__(self, host: str, puerto: int = 3333):
        self.s = socket.create_connection((host, puerto), timeout=3)
        self.s.settimeout(0.05)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.nombre = f"wifi:{host}:{puerto}"

    def leer(self) -> bytes:
        try:
            d = self.s.recv(65536)
            if d == b"":
                raise ConnectionError("TCP cerrado por el S3")
            return d
        except socket.timeout:
            return b""

    def escribir(self, datos: bytes) -> None:
        self.s.sendall(datos)

    def cerrar(self) -> None:
        try:
            self.s.close()
        except OSError:
            pass


def puertos_candidatos() -> list[str]:
    if not list_ports:
        return []
    ps = [p for p in list_ports.comports() if p.vid in VIDS_CONOCIDOS]
    return [p.device for p in ps]


class GestorEnlace(threading.Thread):
    def __init__(self, al_recibir: Callable[[Trama], None], modo: str = "auto",
                 puerto: str | None = None, baud: int = 921600,
                 hosts: tuple[str, ...] = ("192.168.4.1",), puerto_tcp: int = 3333,
                 al_cambiar: Callable[[str], None] | None = None):
        super().__init__(daemon=True)
        self.al_recibir, self.al_cambiar = al_recibir, al_cambiar or (lambda s: None)
        self.modo, self.puerto, self.baud = modo, puerto, baud
        self.hosts, self.puerto_tcp = hosts, puerto_tcp
        self.t: Transporte | None = None
        self.lock = threading.Lock()
        self.ult_rx = 0.0
        self.estado = "desconectado"
        self._parar = threading.Event()

    # ------------------------------------------------------------------ API
    def enviar(self, datos: bytes) -> bool:
        with self.lock:
            if not self.t:
                return False
            try:
                self.t.escribir(datos)
                return True
            except Exception:
                return False

    def parar(self) -> None:
        self._parar.set()

    # ------------------------------------------------------------ internos
    def _probar(self, fabrica) -> Transporte | None:
        """Abre un transporte, envía HELLO y espera la respuesta del S3."""
        try:
            t = fabrica()
        except Exception:
            return None
        dec = Decodificador()
        try:
            for _ in range(3):
                t.escribir(comando("hello"))
                fin = time.time() + 0.5
                while time.time() < fin:
                    for tr in dec.alimentar(t.leer()):
                        if tr.tipo == T_HELLO:
                            self.al_recibir(tr)
                            return t
        except Exception:
            pass
        t.cerrar()
        return None

    def _conectar(self) -> Transporte | None:
        if self.modo in ("auto", "serie") and serial:              # 1) USB/COM primero
            for p in ([self.puerto] if self.puerto else puertos_candidatos()):
                t = self._probar(lambda p=p: TransporteSerie(p, self.baud))
                if t:
                    return t
        if self.modo in ("auto", "wifi"):                          # 2) Wi-Fi: anuncio UDP + lista fija
            hosts = list(dict.fromkeys(descubrir() + list(self.hosts)))
            for h in hosts:
                t = self._probar(lambda h=h: TransporteTCP(h, self.puerto_tcp))
                if t:
                    return t
        return None

    def _set_estado(self, s: str) -> None:
        if s != self.estado:
            self.estado = s
            self.al_cambiar(s)

    def run(self) -> None:
        while not self._parar.is_set():
            t = self._conectar()
            if not t:
                self._set_estado("buscando")
                time.sleep(2)
                continue
            with self.lock:
                self.t = t
            self.ult_rx = time.time()
            self._set_estado(t.nombre)
            dec, t_hb = Decodificador(), 0.0
            try:
                while not self._parar.is_set():
                    d = t.leer()
                    if d:
                        for tr in dec.alimentar(d):
                            self.ult_rx = time.time()
                            self.al_recibir(tr)
                    ahora = time.time()
                    if ahora - t_hb > 1.0:
                        t_hb = ahora
                        self.enviar(comando("hb"))
                    if ahora - self.ult_rx > 5.0:
                        raise TimeoutError("sin tramas en 5 s")
            except Exception as e:
                print(f"[enlace] {t.nombre} caído: {e}")
            with self.lock:
                self.t = None
            t.cerrar()
            self._set_estado("desconectado")
