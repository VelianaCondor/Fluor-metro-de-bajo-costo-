"""
app.py — Página web local del fluorómetro (FastAPI + WebSocket + Plotly), v0.2.

Uso:
  pip install -r requirements.txt
  python app.py                          # decide solo: COM si el S3 está por USB, si no Wi-Fi
  python app.py --modo serie --puerto COM5
  python app.py --modo wifi              # encuentra la IP del S3 por su anuncio UDP (router o red propia)
  python app.py --modo wifi --host 192.168.1.50
  Abrir http://127.0.0.1:8000
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

import procesamiento as proc
from almacenamiento import Sesion
from enlace import GestorEnlace
from protocolo import Trama, comando, interpretar

BASE = Path(__file__).parent
ap = argparse.ArgumentParser()
ap.add_argument("--modo", choices=["auto", "serie", "wifi"], default="auto")
ap.add_argument("--puerto", default=None, help="COMx o /dev/ttyUSBx (por defecto se busca solo)")
ap.add_argument("--baud", type=int, default=921600)
ap.add_argument("--host", action="append", default=None, help="IP del S3 (repetible); además se usa el anuncio UDP")
ap.add_argument("--puerto-tcp", type=int, default=3333)
ap.add_argument("--http", type=int, default=8000)
ap.add_argument("--rgb565-le", action="store_true", help="interpretar RGB565 little-endian")
args = ap.parse_args()

(BASE / "datos").mkdir(exist_ok=True)
sesion = Sesion(BASE / "datos")
clientes: set[WebSocket] = set()
loop: asyncio.AbstractEventLoop | None = None
cola: asyncio.Queue | None = None

# Estado de procesamiento (vive en la PC, no en el S3)
estado = {
    "blanco": None,               # último análisis de intensidad marcado como blanco
    "proximo_es_blanco": False,
    "punto_uniformidad": None,    # {x, y} a asignar a la próxima medición de intensidad
    "uniformidad": [],            # [{x, y, F}]
    "validacion": [],             # [{muestra, etiqueta, ref, F}]
    "repet": {},                  # muestra -> [F]
    "ultimo_F": None,
    "plano": None,                # campo plano (np.ndarray) para el mapa de la cámara
    "cuadros": {},                # captura_id -> {"oscuro": arr, "luz": arr}
    "ultima_dif": None,
}
historial = {"pd": deque(maxlen=3000), "ultimo": {}}


def publicar(ev: dict) -> None:
    """Llamado desde el hilo del enlace: pasa el evento al bucle asyncio de forma segura."""
    if loop and cola:
        loop.call_soon_threadsafe(cola.put_nowait, ev)


def resumen_caracterizacion() -> dict:
    rep = estado["repet"].get(sesion.n_muestra, [])
    return {"ev": "carac", "uniformidad": {**proc.uniformidad(estado["uniformidad"]), "puntos": estado["uniformidad"]},
            "validacion": {**proc.validacion(estado["validacion"]), "pares": estado["validacion"]},
            "repetibilidad": proc.repetibilidad(rep), "blanco": (estado["blanco"] or {}).get("param", {}).get("F"),
            "campo_plano": estado["plano"] is not None}


def procesar_captura(cid: int) -> None:
    c = estado["cuadros"].get(cid, {})
    if "luz" not in c:
        return
    res, imgs = proc.analizar_fluorescencia(c["luz"], c.get("oscuro"), estado["plano"])
    estado["ultima_dif"] = imgs["dif"]
    n = f"cap_{cid}"
    sesion.ruta(n + "_luz.png").write_bytes(proc.png_bytes(c["luz"]))
    if c.get("oscuro") is not None:
        sesion.ruta(n + "_oscuro.png").write_bytes(proc.png_bytes(c["oscuro"]))
    sesion.ruta(n + "_mapa.png").write_bytes(proc.png_bytes(proc.mapa_calor(imgs["dif"], imgs.get("hoja"), imgs.get("baja"))))
    sesion.guardar_captura(cid, {**c, **imgs}, res)
    ev = {"ev": "img", "captura_id": cid, "muestra": sesion.n_muestra, "url_luz": sesion.url(n + "_luz.png"),
          "url_oscuro": sesion.url(n + "_oscuro.png") if c.get("oscuro") is not None else None,
          "url_mapa": sesion.url(n + "_mapa.png"), **res}
    historial["ultimo"]["img"] = ev
    publicar(ev)


def al_recibir(tr: Trama) -> None:
    try:
        d = interpretar(tr)
    except Exception as e:
        publicar({"ev": "log", "texto": f"Error interpretando {tr.nombre}: {e}"})
        return
    tipo = d["_tipo"]
    if tipo == "pd":
        sesion.guardar_pd(d)
        historial["pd"].extend(zip(d["t"], d["vn"]))
        publicar({"ev": "pd", "t": d["t"], "vn": d["vn"], "s": d["s"], "led": d.get("led", 0)})
    elif tipo == "term":
        sesion.guardar_term(d)
        publicar({"ev": "term", **{k: v for k, v in d.items() if k != "_tipo"}})
    elif tipo == "ojip":
        an = proc.analizar_ojip(d)
        sesion.guardar_ojip(d, an)
        ev = {"ev": "ojip", "id": d["id"], "t": d["t"], "v": d["v"], "muestra": sesion.n_muestra,
              "cab": {k: d[k] for k in ("n_muestras", "dur_ms", "fs_hz", "v_dark", "ruido_dark", "sat", "T1", "T2")}, **an}
        historial["ultimo"]["ojip"] = ev
        publicar(ev)
    elif tipo == "int":
        es_blanco = estado["proximo_es_blanco"]
        an = proc.analizar_intensidad(d, None if es_blanco else estado["blanco"])
        sesion.guardar_int(d, an, es_blanco)
        F = an["param"].get("F_neta", an["param"].get("F"))
        if es_blanco:
            estado["blanco"], estado["proximo_es_blanco"] = an, False
            sesion.notas({"blanco": True})
        elif F is not None:
            estado["ultimo_F"] = F
            estado["repet"].setdefault(sesion.n_muestra, []).append(F)
            if estado["punto_uniformidad"]:
                estado["uniformidad"].append({**estado["punto_uniformidad"], "F": F})
                estado["punto_uniformidad"] = None
                sesion.guardar_tabla("uniformidad.csv", estado["uniformidad"])
        ev = {"ev": "int", "id": d["id"], "t": d["t"], "v": d["v"], "blanco": es_blanco, "muestra": sesion.n_muestra,
              "dur_ms": d["dur_ms"], "t_foto_ms": d["t_foto_ms"], "foto": d["foto"], **an}
        historial["ultimo"]["int"] = ev
        publicar(ev)
        publicar(resumen_caracterizacion())
    elif tipo == "img":
        arr = proc.a_gris(d["datos"], d["ancho"], d["alto"], d["formato"], big_endian=not args.rgb565_le)
        c = estado["cuadros"].setdefault(d["captura_id"], {})
        c[d["rol_txt"]] = arr
        if d["rol_txt"] == "luz":
            procesar_captura(d["captura_id"])
    else:
        publicar({"ev": tipo, **{k: v for k, v in d.items() if k != "_tipo"}})


enlace = GestorEnlace(al_recibir, modo=args.modo, puerto=args.puerto, baud=args.baud,
                      hosts=tuple(args.host or ["192.168.4.1"]), puerto_tcp=args.puerto_tcp,
                      al_cambiar=lambda s: publicar({"ev": "enlace", "estado": s}))


async def difundir() -> None:
    while True:
        ev = await cola.get()
        txt = json.dumps(ev, default=float)
        for ws in list(clientes):
            try:
                await ws.send_text(txt)
            except Exception:
                clientes.discard(ws)


@asynccontextmanager
async def ciclo_de_vida(_app):
    global loop, cola
    loop, cola = asyncio.get_running_loop(), asyncio.Queue()
    enlace.start()
    tarea = asyncio.create_task(difundir())
    yield
    enlace.parar()
    tarea.cancel()


app = FastAPI(title="Fluorómetro de clorofila", lifespan=ciclo_de_vida)
app.mount("/datos", StaticFiles(directory=BASE / "datos"), name="datos")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
async def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/plotly.min.js")
async def plotly_js():
    """Plotly servido desde el paquete pip: la página funciona sin internet."""
    try:
        import plotly
        return FileResponse(Path(plotly.__file__).parent / "package_data" / "plotly.min.js",
                            media_type="application/javascript")
    except Exception:
        return Response("console.error('Instala plotly: pip install plotly')", media_type="application/javascript")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clientes.add(ws)
    await ws.send_text(json.dumps({"ev": "enlace", "estado": enlace.estado}))
    await ws.send_text(json.dumps({"ev": "muestra", "n": sesion.n_muestra, "etiqueta": sesion.etiqueta}))
    if historial["pd"]:
        t, v = zip(*historial["pd"])
        await ws.send_text(json.dumps({"ev": "pd", "t": t, "vn": v, "s": [0] * len(t)}))
    for ev in historial["ultimo"].values():
        await ws.send_text(json.dumps(ev, default=float))
    await ws.send_text(json.dumps(resumen_caracterizacion(), default=float))
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        clientes.discard(ws)


LOCALES = {"nueva_muestra", "marcar_blanco", "borrar_blanco", "punto_uniformidad", "borrar_uniformidad",
           "ref_validacion", "borrar_validacion", "campo_plano", "borrar_campo_plano"}


@app.post("/api/cmd")
async def api_cmd(cuerpo: dict):
    cmd = cuerpo.pop("cmd", "")
    if cmd in LOCALES:                                   # comandos que resuelve la PC
        if cmd == "nueva_muestra":
            n = sesion.nueva_muestra(cuerpo.get("etiqueta", ""))
            publicar({"ev": "muestra", "n": n, "etiqueta": sesion.etiqueta})
        elif cmd == "marcar_blanco":
            estado["proximo_es_blanco"] = True
        elif cmd == "borrar_blanco":
            estado["blanco"] = None
        elif cmd == "punto_uniformidad":
            estado["punto_uniformidad"] = {"x": float(cuerpo["x"]), "y": float(cuerpo["y"])}
        elif cmd == "borrar_uniformidad":
            estado["uniformidad"].clear(); sesion.guardar_tabla("uniformidad.csv", [])
        elif cmd == "ref_validacion":
            if estado["ultimo_F"] is None:
                return JSONResponse({"ok": False, "error": "primero mide la intensidad de la muestra"}, 409)
            estado["validacion"].append({"muestra": sesion.n_muestra, "etiqueta": sesion.etiqueta,
                                         "ref": float(cuerpo["valor"]), "F": estado["ultimo_F"]})
            sesion.guardar_tabla("validacion.csv", estado["validacion"])
        elif cmd == "borrar_validacion":
            estado["validacion"].clear(); sesion.guardar_tabla("validacion.csv", [])
        elif cmd == "campo_plano":
            if estado["ultima_dif"] is None:
                return JSONResponse({"ok": False, "error": "no hay captura previa"}, 409)
            estado["plano"] = estado["ultima_dif"].copy()
        elif cmd == "borrar_campo_plano":
            estado["plano"] = None
        publicar(resumen_caracterizacion())
        return {"ok": True}
    ok = enlace.enviar(comando(cmd, **cuerpo))
    return JSONResponse({"ok": ok, "enlace": enlace.estado}, status_code=200 if ok else 503)


@app.get("/api/estado")
async def api_estado():
    return {"enlace": enlace.estado, "sesion": str(sesion.dir), "muestra": sesion.n_muestra, "t": time.time()}


@app.get("/api/estabilidad")
async def api_estabilidad(ventana_s: float = 60, criterio_pct: float = 1.0):
    if not historial["pd"]:
        return {"n": 0}
    t, v = zip(*historial["pd"])
    return proc.estabilidad([x / 1000 for x in t], list(v), ventana_s, criterio_pct)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=args.http, log_level="warning")
