"""
simulador_s3.py — Imita al ESP32-S3 maestro (protocolo v0.2) para desarrollar la página sin hardware.

  python simulador_s3.py                 # servidor TCP en 127.0.0.1:3333 + anuncio UDP local
  python app.py --modo wifi              # la app lo encuentra por el anuncio
  python simulador_s3.py --pty           # (Linux/macOS) puerto serie virtual
  python app.py --modo serie --puerto /dev/pts/N

Genera telemetría del fotodiodo, estado térmico (2 lazos PI), mediciones de intensidad con foto
de fluorescencia (cuadro oscuro + cuadro con LED, GRAY8), curvas OJIP sintéticas y logs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import socket
import threading
import time
import zlib

import numpy as np

from protocolo import (BIN_OJIP, CAB_IMG, CAB_INT, CAB_OJIP, PT_INT, T_CMD, T_ESTADO, T_HELLO, T_IMG, T_INT,
                       T_LOG, T_OJIP, T_PD, T_RESP, T_TERM, Decodificador, codificar)


def curva_ojip(dur_ms=1000, fs=40000, fvfm=0.82, ruido=0.6e-3, f0=0.40):
    fm = f0 / (1 - fvfm); fv = fm - f0
    t = np.arange(1, int(dur_ms / 1000 * fs) + 1) / fs
    f = (f0 + 0.45 * fv * (1 - np.exp(-t / 0.4e-3)) + 0.25 * fv * (1 - np.exp(-t / 12e-3))
         + 0.30 * fv * (1 - np.exp(-t / 120e-3)))
    f += np.random.normal(0, ruido, f.size)
    tus = t * 1e6
    k = np.where(tus < 10, 0, 1 + np.floor((np.log10(tus) - 1) * 30)).astype(int)
    return [(float(t[k == kk].mean()), float(f[k == kk].mean()), int((k == kk).sum())) for kk in np.unique(k)], t.size, fs, ruido


def curva_intensidad(dur_ms, nivel, ruido=0.4e-3):
    """Fluorescencia con luz continua: subida rápida, pico y descenso lento (efecto Kautsky)."""
    t = np.arange(0, dur_ms / 1000, 0.02) + 0.017
    fs = 0.65 * nivel
    f = (fs + (nivel - fs) * np.exp(-np.clip(t - 0.3, 0, None) / 1.5)) * (1 - np.exp(-t / 0.02))
    return t, f + np.random.normal(0, ruido, t.size)


def cuadros(nivel: float, captura_id: int):
    h, w = 120, 160
    y, x = np.mgrid[0:h, 0:w]
    ilum = np.exp(-(((x - 80) / 70) ** 2 + ((y - 60) / 55) ** 2))          # iluminación no uniforme
    hoja = ((x - 78) / 58) ** 2 + ((y - 62) / 42) ** 2 < 1
    mancha = ((x - 100) / 12) ** 2 + ((y - 50) / 10) ** 2 < 1              # zona dañada (menos fluorescencia)
    fluo = np.where(hoja, 1.0, 0.03) * np.where(mancha, 0.35, 1.0)
    oscuro = 8 + np.random.normal(0, 1.5, (h, w))
    luz = oscuro + 170 * nivel / 1.0 * fluo * ilum + np.random.normal(0, 2.0, (h, w))
    return oscuro.clip(0, 255).astype(np.uint8), luz.clip(0, 255).astype(np.uint8)


class S3Simulado:
    def __init__(self, escribir):
        self.escribir, self.seq = escribir, 0
        self.T, self.u, self.integ = [26.0, 26.5], [0.0, 0.0], [0.0, 0.0]
        self.sp = [27.0, 27.0]
        self.led = False
        self.id_med, self.foto_id = 0, 0
        self.t_foto, self.vivo = 1000, True
        self.dec = Decodificador()

    def tx(self, tipo, payload: bytes):
        self.seq += 1
        self.escribir(codificar(tipo, payload, self.seq))

    def txj(self, tipo, d):
        self.tx(tipo, json.dumps(d).encode())

    def enviar_cuadro(self, img: np.ndarray, cid: int, rol: int):
        self.foto_id += 1
        datos = img.tobytes()
        cab = CAB_IMG.pack(self.foto_id, cid, rol, 160, 120, 2, zlib.crc32(datos), len(datos), int(time.time() * 1000) & 0xFFFFFFFF)
        self.tx(T_IMG, cab + datos)

    def intensidad(self, dur_ms, foto, blanco=False):
        self.id_med += 1
        nivel = random.uniform(0.02, 0.04) if blanco else random.uniform(0.25, 0.9)
        time.sleep(0.4 + dur_ms / 1000)
        t, f = curva_intensidad(dur_ms, nivel)
        tf = min(self.t_foto, dur_ms - 100) / 1000
        m = (t >= tf) & (t < tf + 0.15)
        cab = CAB_INT.pack(self.id_med, self.id_med if foto else 0, len(t), dur_ms, int(tf * 1000), 0.012, 0.4e-3,
                           float(f[m].mean()) if m.any() else 0.0, float(f[m].std()) if m.any() else 0.0,
                           int(foto), 0, self.T[0], self.T[1])
        self.tx(T_INT, cab + b"".join(PT_INT.pack(a, b) for a, b in zip(t, f)))
        if foto:
            osc, luz = cuadros(float(f[m].mean()) if m.any() else nivel, self.id_med)
            time.sleep(0.6)
            self.enviar_cuadro(osc, self.id_med, 0)
            time.sleep(0.6)
            self.enviar_cuadro(luz, self.id_med, 1)
            self.txj(T_LOG, f"Captura {self.id_med}: cuadros OSCURO y LUZ recibidos")

    def ojip(self, dur_ms, led):
        self.id_med += 1
        time.sleep(dur_ms / 1000 + 0.15)
        bins, n, fs, ruido = curva_ojip(dur_ms, fvfm=random.uniform(0.74, 0.84))
        if not led:
            bins = [(t, random.gauss(0, ruido), c) for t, _, c in bins]
        cab = CAB_OJIP.pack(self.id_med, len(bins), n, dur_ms, fs, 0.012, ruido, 0, int(led), self.T[0], self.T[1])
        self.tx(T_OJIP, cab + b"".join(BIN_OJIP.pack(*b) for b in bins))

    def comando(self, j):
        c = j.get("cmd")
        if c == "hello":
            self.txj(T_HELLO, {"dev": "fluorometro-s3-SIMULADO", "fw": "0.2", "enlace": "sim", "modo": 0, "wifi": "router"})
            return
        if c == "hb":
            return
        if c in ("intensidad", "foto"):
            threading.Thread(target=self.intensidad, args=(int(j.get("dur_ms", 2000)), int(j.get("foto", c == "foto")),
                                                              bool(j.get("blanco", 0))), daemon=True).start()
        elif c == "ojip":
            threading.Thread(target=self.ojip, args=(int(j.get("dur_ms", 1000)), int(j.get("led", 1))), daemon=True).start()
        elif c == "led":
            self.led = bool(j.get("on"))
        elif c == "cam":
            self.t_foto = int(j.get("t_foto_ms", self.t_foto))
        elif c == "sp":
            for i in range(2):
                if j.get("n", -1) in (-1, i):
                    self.sp[i] = float(j["valor"])
        elif c == "dark":
            self.txj(T_LOG, "Offset oscuridad = 0.01200 V (50 muestras)")
        self.txj(T_RESP, {"ok": 1, "cmd": c})

    def recibir(self, datos: bytes):
        for tr in self.dec.alimentar(datos):
            if tr.tipo == T_CMD:
                self.comando(json.loads(tr.payload))

    def bucle(self):
        t_ini = time.time(); t_term = t_est = t_ini; t_led = None
        while self.vivo:
            ahora = time.time()
            if self.led and t_led is None:
                t_led = ahora
            if not self.led:
                t_led = None
            base = 0.01
            if t_led is not None:                     # LED continuo: deriva térmica que se estabiliza
                base = 0.5 * (1 - 0.04 * (1 - math.exp(-(ahora - t_led) / 40)))
            ms = [int((ahora - t_ini) * 1000 + i * 20) for i in range(5)]
            vt = [base + random.gauss(0, 0.0004) for _ in ms]
            self.txj(T_PD, {"t": ms, "vt": vt, "vn": vt, "s": [0] * 5, "led": int(self.led)})
            if ahora - t_term >= 1:
                t_term = ahora
                calor = [0.12 if self.led else 0.04, 0.05]
                for i in range(2):
                    self.T[i] += 0.5 * (calor[i] * (31 - self.T[i]) - 0.0012 * self.u[i] * (self.T[i] - 25.0) * 10)
                    e = self.T[i] - self.sp[i]
                    self.integ[i] = min(max(self.integ[i] + 0.5 * e, 0), 100)
                    u = min(max(20 * e + self.integ[i], 0), 100)
                    self.u[i] = 0 if u < 5 else max(u, 30)
                self.txj(T_TERM, {"t": int((ahora - t_ini) * 1000), "sp": self.sp, "T": self.T, "RH": [55.0, 54.2],
                                  "u": self.u, "ok": [1, 1], "sp_inalc": [0, 0], "manual": [0, 0]})
            if ahora - t_est >= 1:
                t_est = ahora
                self.txj(T_ESTADO, {"up": int((ahora - t_ini) * 1000), "enlace": "sim", "modo": 0, "wifi": "router",
                                    "ip": "127.0.0.1", "rssi": -55, "cam": 1, "cam_hace_ms": 1200, "led": int(self.led)})
            time.sleep(0.1)


def anunciar(puerto_tcp):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    msg = json.dumps({"dev": "fluorometro-s3", "ip": "127.0.0.1", "tcp": puerto_tcp, "wifi": "router"}).encode()
    while True:
        try:
            s.sendto(msg, ("127.0.0.1", 3334))
        except OSError:
            pass
        time.sleep(2)


def servir_tcp(host, puerto):
    threading.Thread(target=anunciar, args=(puerto,), daemon=True).start()
    srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, puerto)); srv.listen(1)
    print(f"Simulador S3 escuchando en {host}:{puerto}")
    while True:
        c, a = srv.accept()
        print("PC conectada:", a)
        lock = threading.Lock()

        def escribir(b, c=c):
            with lock:
                c.sendall(b)
        s3 = S3Simulado(escribir)
        threading.Thread(target=s3.bucle, daemon=True).start()
        try:
            while True:
                d = c.recv(4096)
                if not d:
                    break
                s3.recibir(d)
        except OSError:
            pass
        s3.vivo = False
        c.close()


def servir_pty():
    import pty
    import tty
    maestro, esclavo = pty.openpty()
    tty.setraw(esclavo)
    print("Puerto serie virtual:", os.ttyname(esclavo))
    lock = threading.Lock()

    def escribir(b):
        with lock:
            os.write(maestro, b)
    s3 = S3Simulado(escribir)
    threading.Thread(target=s3.bucle, daemon=True).start()
    while True:
        s3.recibir(os.read(maestro, 4096))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pty", action="store_true")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=3333)
    a = ap.parse_args()
    servir_pty() if a.pty else servir_tcp(a.host, a.puerto)
