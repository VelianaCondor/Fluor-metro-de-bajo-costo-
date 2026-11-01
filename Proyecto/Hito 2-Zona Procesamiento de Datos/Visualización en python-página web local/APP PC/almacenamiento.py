"""
almacenamiento.py — Organiza en disco todo lo que llega del fluorómetro (v0.2).

datos/
  sesion_AAAAMMDD_HHMMSS/
    telemetria_fotodiodo.csv      (t_ms, V_tia, V_neta, sat, led)
    termico.csv                   (t_ms, sp_inf, sp_sup, T_inf, T_sup, RH_inf, RH_sup, u_inf, u_sup)
    uniformidad.csv, validacion.csv   (pruebas de caracterización óptica)
    muestra_001/
      notas.json                      (etiqueta, si es blanco)
      int_<id>.csv / .json            (medición de intensidad y su análisis)
      ojip_<id>.csv / .json           (curva OJIP y JIP-test)
      cap_<id>_luz.png, cap_<id>_oscuro.png, cap_<id>_mapa.png, cap_<id>.npz, cap_<id>.json
"""
from __future__ import annotations

import csv
import json
import time
from pathlib import Path

import numpy as np


class Sesion:
    def __init__(self, raiz: str | Path = "datos"):
        self.dir = Path(raiz) / time.strftime("sesion_%Y%m%d_%H%M%S")
        self.dir.mkdir(parents=True, exist_ok=True)
        self.n_muestra = 0
        self.etiqueta = ""
        self._pd = open(self.dir / "telemetria_fotodiodo.csv", "w", newline="")
        self._pdw = csv.writer(self._pd); self._pdw.writerow(["t_ms", "V_tia", "V_neta", "sat", "led"])
        self._te = open(self.dir / "termico.csv", "w", newline="")
        self._tew = csv.writer(self._te)
        self._tew.writerow(["t_ms", "sp_inf", "sp_sup", "T_inf", "T_sup", "RH_inf", "RH_sup", "u_inf", "u_sup"])
        self.nueva_muestra()

    @property
    def dir_muestra(self) -> Path:
        return self.dir / f"muestra_{self.n_muestra:03d}"

    def nueva_muestra(self, etiqueta: str = "") -> int:
        self.n_muestra += 1
        self.etiqueta = etiqueta
        self.dir_muestra.mkdir(exist_ok=True)
        self.notas({"muestra": self.n_muestra, "etiqueta": etiqueta, "inicio": time.time()})
        return self.n_muestra

    def notas(self, d: dict) -> None:
        f = self.dir_muestra / "notas.json"
        previo = json.loads(f.read_text()) if f.exists() else {}
        f.write_text(json.dumps({**previo, **d}, indent=2))

    def guardar_pd(self, d: dict) -> None:
        led = d.get("led", 0)
        for fila in zip(d["t"], d["vt"], d["vn"], d["s"]):
            self._pdw.writerow([*fila, led])
        self._pd.flush()

    def guardar_term(self, d: dict) -> None:
        self._tew.writerow([d["t"], *d["sp"], *d["T"], *d["RH"], *d["u"]])
        self._te.flush()

    def ruta(self, nombre: str) -> Path:
        return self.dir_muestra / nombre

    def url(self, nombre: str) -> str:
        return f"/datos/{self.dir.name}/{self.dir_muestra.name}/{nombre}"

    def _curva(self, nombre: str, cab: list[str], filas) -> None:
        with open(self.ruta(nombre), "w", newline="") as fh:
            w = csv.writer(fh); w.writerow(cab); w.writerows(filas)

    def guardar_ojip(self, d: dict, analisis: dict) -> None:
        self._curva(f"ojip_{d['id']}.csv", ["t_s", "F_V", "n"], zip(d["t"], d["v"], d["n"]))
        meta = {k: v for k, v in d.items() if k not in ("t", "v", "n")}
        self.ruta(f"ojip_{d['id']}.json").write_text(json.dumps({"cabecera": meta, **analisis}, indent=2, default=str))

    def guardar_int(self, d: dict, analisis: dict, es_blanco: bool) -> None:
        self._curva(f"int_{d['id']}.csv", ["t_s", "F_V"], zip(d["t"], d["v"]))
        meta = {k: v for k, v in d.items() if k not in ("t", "v")}
        self.ruta(f"int_{d['id']}.json").write_text(json.dumps({"cabecera": meta, "blanco": es_blanco, **analisis},
                                                               indent=2, default=str))

    def guardar_captura(self, cid: int, imgs: dict, resultado: dict) -> None:
        np.savez_compressed(self.ruta(f"cap_{cid}.npz"), **{k: v for k, v in imgs.items() if isinstance(v, np.ndarray)})
        self.ruta(f"cap_{cid}.json").write_text(json.dumps(resultado, indent=2, default=str))

    def guardar_tabla(self, nombre: str, filas: list[dict]) -> None:
        if not filas:
            (self.dir / nombre).unlink(missing_ok=True)
            return
        with open(self.dir / nombre, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(filas[0].keys())); w.writeheader(); w.writerows(filas)
