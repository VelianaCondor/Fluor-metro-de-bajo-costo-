"""
procesamiento.py — Análisis de las mediciones del fluorómetro (v0.2). Solo depende de numpy y Pillow.

  1. OJIP / JIP-test       : curva rápida con hoja adaptada a oscuridad (Fv/Fm, VJ, M0, PIabs...)
  2. Intensidad            : fluorescencia con el LED encendido un tiempo fijo, con resta de línea base y blanco
  3. Imagen de fluorescencia: cuadro con LED − cuadro oscuro, detrás del filtro pasa-largo de 650 nm
  4. Caracterización óptica: estabilidad, uniformidad (Urel), validación contra el equipo de referencia
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

# ============================== 1. OJIP / JIP-test ==============================
T_F0, T_K, T_J, T_I = 50e-6, 300e-6, 2e-3, 30e-3     # tiempos característicos (s)


def _f_en(t: np.ndarray, f: np.ndarray, tq: float) -> float:
    """Interpola F en el tiempo tq usando eje logarítmico (como se grafica la OJIP)."""
    return float(np.interp(np.log10(tq), np.log10(t), f))


def _mediana3(x: np.ndarray) -> np.ndarray:
    if len(x) < 3:
        return x.copy()
    p = np.pad(x, 1, mode="edge")
    return np.median(np.stack([p[:-2], p[1:-1], p[2:]]), axis=0)


def _trap(y, x) -> float:
    return float(np.trapezoid(y, x)) if hasattr(np, "trapezoid") else float(np.trapz(y, x))


def analizar_ojip(d: dict) -> dict:
    """d: diccionario 'ojip' del protocolo (t [s], v [V sin offset], n, fs_hz, ruido_dark, sat, dur_ms)."""
    t = np.asarray(d["t"], float)
    f = np.asarray(d["v"], float)
    ok = t > 0
    t, f = t[ok], f[ok]
    avisos: list[str] = []
    if len(t) < 10:
        return {"ok": False, "avisos": ["Curva con muy pocos puntos"], "param": {}}

    if t[0] <= T_F0:
        F0 = _f_en(t, f, T_F0)
    else:
        F0 = float(f[0])
        avisos.append(f"Primer punto a {t[0]*1e6:.0f} µs (> 50 µs): F0 poco confiable (sobreestimado)")
    fs = _mediana3(f)
    i_m = int(np.argmax(fs))
    FM, tFM = float(fs[i_m]), float(t[i_m])
    FK, FJ, FI = (_f_en(t, f, x) for x in (T_K, T_J, T_I))
    Fv = FM - F0

    p = {"F0": F0, "FK": FK, "FJ": FJ, "FI": FI, "FM": FM, "tFM_ms": tFM * 1e3, "Fv": Fv}
    if Fv <= 0 or FM <= 0:
        avisos.append("No hay subida de fluorescencia: ¿LED apagado, sin muestra o hoja no adaptada?")
        return {"ok": False, "avisos": avisos, "param": p}

    VJ = (FJ - F0) / Fv
    VI = (FI - F0) / Fv
    M0 = 4.0 * (FK - F0) / Fv
    FvFm = Fv / FM
    area = _trap(FM - fs[: i_m + 1], t[: i_m + 1])
    psiE0 = 1.0 - VJ
    phiE0 = FvFm * psiE0
    PIabs = None
    if 0 < FvFm < 1 and 0 < psiE0 < 1 and M0 > 0:
        PIabs = FvFm * (VJ / M0) * (FvFm / (1 - FvFm)) * (psiE0 / (1 - psiE0))
    p.update({"Fv_Fm": FvFm, "Fv_F0": Fv / F0 if F0 > 0 else None, "VJ": VJ, "VI": VI, "M0": M0,
              "Area_Vs": area, "Sm_ms": area / Fv * 1e3, "psiE0": psiE0, "phiE0": phiE0, "PIabs": PIabs})

    if d.get("sat"):
        avisos.append("Señal saturada: bajar la potencia del LED o la ganancia de la etapa")
    if tFM > 0.9 * d.get("dur_ms", 1000) / 1000:
        avisos.append("FM al final de la ventana: alargar la captura o subir la intensidad (sin saturar)")
    ruido = d.get("ruido_dark", 0) or 0
    snr = Fv / ruido if ruido > 0 else float("inf")
    p["SNR"] = snr if np.isfinite(snr) else None
    if snr < 20:
        avisos.append(f"SNR bajo (Fv/ruido = {snr:.0f}): revisar luz parásita y blindaje")
    if not 0.0 < FvFm < 0.9:
        avisos.append("Fv/Fm fuera de rango fisiológico: revisar offset de oscuridad y blanco")
    if d.get("fs_hz", 0) < 20000:
        avisos.append(f"Muestreo de {d.get('fs_hz', 0)/1000:.1f} kS/s: fase O-J poco resuelta")

    return {"ok": True, "avisos": avisos, "param": p, "interpretacion": interpretar_ojip(p),
            "marcas": {"O": [T_F0, F0], "K": [T_K, FK], "J": [T_J, FJ], "I": [T_I, FI], "P": [tFM, FM]}}


def interpretar_ojip(p: dict) -> list[str]:
    """Lectura orientativa (hoja adaptada a oscuridad). Los umbrales son referenciales."""
    r = []
    x = p.get("Fv_Fm")
    if x is None:
        return r
    if x >= 0.78:
        r.append(f"Fv/Fm = {x:.3f}: fotosistema II sin estrés aparente (hojas sanas suelen dar ~0.80-0.84).")
    elif x >= 0.70:
        r.append(f"Fv/Fm = {x:.3f}: estrés leve a moderado o adaptación a oscuridad incompleta.")
    else:
        r.append(f"Fv/Fm = {x:.3f}: estrés marcado o fotoinhibición (o problema de medición: revisar avisos).")
    if p.get("VJ") is not None:
        r.append(f"VJ = {p['VJ']:.2f}: fracción de QA reducida a 2 ms.")
    if p.get("PIabs") is not None:
        r.append(f"PIabs = {p['PIabs']:.2f}: índice de desempeño, útil para comparar muestras del mismo experimento.")
    return r


# ============================== 2. Intensidad ==================================
def analizar_intensidad(d: dict, blanco: dict | None = None, ventana=(0.5, 1.0)) -> dict:
    """
    d: diccionario 'int' (t [s desde que se enciende el LED], v [V, ya sin línea base de LED apagado]).
    La lectura F es el promedio dentro de la ventana relativa (por defecto, la segunda mitad del pulso),
    siempre la misma para que las muestras sean comparables (la fluorescencia cambia con el tiempo de luz).
    blanco: resultado de una medición sobre una referencia NO fluorescente con la misma configuración.
    """
    t = np.asarray(d["t"], float)
    v = np.asarray(d["v"], float)
    avisos: list[str] = []
    if len(t) < 5:
        return {"ok": False, "avisos": ["Muy pocos puntos"], "param": {}}
    dur = d.get("dur_ms", t[-1] * 1000) / 1000
    m = (t >= ventana[0] * dur) & (t <= ventana[1] * dur)
    if m.sum() < 3:
        m = t >= t[len(t) // 2]
    F, sd = float(v[m].mean()), float(v[m].std(ddof=1)) if m.sum() > 1 else 0.0
    pend = float(np.polyfit(t[m], v[m], 1)[0]) if m.sum() > 2 else 0.0
    deriva = pend * (t[m][-1] - t[m][0]) / F * 100 if F else 0.0
    i_pico = int(np.argmax(v))
    p = {"F": F, "sd": sd, "RSD_pct": abs(sd / F * 100) if F else None, "deriva_pct": deriva,
         "F_pico": float(v[i_pico]), "t_pico_s": float(t[i_pico]), "F_final": float(v[-5:].mean()),
         "ventana_s": [float(ventana[0] * dur), float(ventana[1] * dur)], "ruido_dark": d.get("ruido_dark")}
    if d.get("foto"):
        p["F_durante_foto"] = d.get("v_foto")
    if blanco and blanco.get("param", {}).get("F") is not None:
        p["F_blanco"] = blanco["param"]["F"]
        p["F_neta"] = F - blanco["param"]["F"]
    else:
        avisos.append("Sin blanco: F incluye luz de excitación reflejada o dispersada que pase el filtro")
    if d.get("sat"):
        avisos.append("Señal saturada durante el pulso")
    if abs(deriva) > 5:
        avisos.append(f"Deriva de {deriva:+.1f} % dentro de la ventana: LED o muestra aún no estables")
    rd = d.get("ruido_dark") or 0
    if rd and F / rd < 20:
        avisos.append(f"SNR bajo (F/ruido = {F/rd:.0f})")
    return {"ok": True, "avisos": avisos, "param": p}


# ======================= 3. Imagen de fluorescencia ============================
def a_gris(datos: bytes, ancho: int, alto: int, formato: int, big_endian: bool = True) -> np.ndarray:
    """GRAY8 directo. RGB565: se usa el canal rojo (detrás del filtro de 650 nm es el que tiene señal)."""
    if formato == 2:
        return np.frombuffer(datos, np.uint8)[: ancho * alto].reshape(alto, ancho).astype(float)
    a = np.frombuffer(datos, dtype=">u2" if big_endian else "<u2").reshape(alto, ancho).astype(np.uint32)
    return (((a >> 11) & 0x1F) * 255 / 31).astype(float)


def _otsu(x: np.ndarray, bins: int = 128) -> float:
    h, e = np.histogram(x, bins=bins)
    c = (e[:-1] + e[1:]) / 2
    w0 = np.cumsum(h); w1 = w0[-1] - w0
    m0 = np.cumsum(h * c) / np.maximum(w0, 1)
    m1 = (np.sum(h * c) - np.cumsum(h * c)) / np.maximum(w1, 1)
    return float(c[np.argmax(w0 * w1 * (m0 - m1) ** 2)])


def _suavizar(x: np.ndarray) -> np.ndarray:
    p = np.pad(x, 1, mode="edge")
    return sum(p[i:i + x.shape[0], j:j + x.shape[1]] for i in range(3) for j in range(3)) / 9


def analizar_fluorescencia(luz: np.ndarray, oscuro: np.ndarray | None, plano: np.ndarray | None = None) -> tuple[dict, dict]:
    """
    luz, oscuro: cuadros en niveles de gris (float). La diferencia elimina el offset del sensor y la luz
    ambiente que se cuele. plano: imagen de una referencia fluorescente uniforme (campo plano), opcional,
    para separar la falta de uniformidad de la iluminación de la variación real de la hoja.
    Devuelve (resultado, imágenes).
    """
    avisos = []
    sat = float((luz >= 250).mean())
    if sat > 0.005:
        avisos.append(f"{sat*100:.1f} % de píxeles saturados: bajar la exposición (AEC) o la ganancia")
    if oscuro is None:
        oscuro = np.zeros_like(luz)
        avisos.append("Sin cuadro oscuro: no se resta el offset del sensor")
    dif = np.clip(luz - oscuro, 0, None)
    if plano is not None and plano.shape == dif.shape:
        pn = _suavizar(plano)
        pn = pn / max(pn[pn > 0.2 * pn.max()].mean(), 1e-6)
        dif = np.where(pn > 0.2, dif / np.maximum(pn, 0.2), 0)
        corr = "con corrección de campo plano"
    else:
        corr = "sin campo plano: el mapa incluye la falta de uniformidad de la iluminación"
    ds = _suavizar(dif)
    if ds.max() < 3:
        avisos.append("Casi sin señal de fluorescencia: subir exposición, revisar LED o filtro")
        return {"ok": False, "avisos": avisos, "correccion": corr, "nivel_oscuro": float(oscuro.mean())}, {"dif": dif}
    umbral = max(_otsu(ds), 0.1 * ds.max())
    hoja = ds > umbral
    vals = dif[hoja]
    med = float(np.median(vals))
    baja = hoja & (ds < 0.6 * med)                           # zonas con fluorescencia < 60 % de la mediana
    res = {
        "ok": True, "avisos": avisos, "correccion": corr,
        "fraccion_area": float(hoja.mean()), "media": float(vals.mean()), "sd": float(vals.std()),
        "CV_pct": float(vals.std() / vals.mean() * 100), "p5": float(np.percentile(vals, 5)),
        "mediana": med, "p95": float(np.percentile(vals, 95)),
        "zonas_bajas_pct": float(baja.sum() / max(hoja.sum(), 1) * 100),
        "nivel_oscuro": float(oscuro.mean()), "saturados_pct": sat * 100,
    }
    if oscuro.mean() > 20:
        res["avisos"].append(f"Cuadro oscuro con nivel {oscuro.mean():.0f}: posible fuga de luz o offset alto")
    return res, {"dif": dif, "hoja": hoja, "baja": baja}


# Paleta tipo "inferno" (aproximada con anclas) para el mapa de calor
_ANCLAS = np.array([[0, 0, 4], [40, 11, 84], [101, 21, 110], [159, 42, 99], [212, 72, 66],
                    [245, 125, 21], [250, 193, 39], [252, 255, 164]], float)


def mapa_calor(x: np.ndarray, hoja: np.ndarray | None = None, baja: np.ndarray | None = None) -> np.ndarray:
    v = x / max(np.percentile(x, 99.5), 1e-6)
    v = np.clip(v, 0, 1) * (len(_ANCLAS) - 1)
    i = np.floor(v).astype(int).clip(0, len(_ANCLAS) - 2)
    w = (v - i)[..., None]
    rgb = _ANCLAS[i] * (1 - w) + _ANCLAS[i + 1] * w
    if baja is not None:                                      # contorno cian en zonas de baja fluorescencia
        borde = baja ^ np.roll(baja, 1, 0) | baja ^ np.roll(baja, 1, 1)
        rgb[borde] = [0, 220, 255]
    return rgb.clip(0, 255).astype(np.uint8)


def png_bytes(img: np.ndarray, escala: int = 1) -> bytes:
    if img.ndim == 2:
        img = np.clip(img, 0, 255).astype(np.uint8)
    im = Image.fromarray(img)
    if escala > 1:
        im = im.resize((img.shape[1] * escala, img.shape[0] * escala), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


# ======================= 4. Caracterización óptica =============================
def uniformidad(puntos: list[dict]) -> dict:
    """puntos: [{x, y, F}]. Urel = (Emax − Emin)/(Emax + Emin) · 100 % (métrica del área óptica) y CV."""
    F = np.array([p["F"] for p in puntos], float)
    if len(F) < 2:
        return {"n": len(F)}
    return {"n": len(F), "Urel_pct": float((F.max() - F.min()) / (F.max() + F.min()) * 100),
            "CV_pct": float(F.std(ddof=1) / F.mean() * 100), "F_max": float(F.max()), "F_min": float(F.min())}


def validacion(pares: list[dict]) -> dict:
    """pares: [{ref, F}] (ref = lectura del espectrofluorómetro). Ajuste y = m·x + b con x = ref, y = F."""
    if len(pares) < 3:
        return {"n": len(pares)}
    x = np.array([p["ref"] for p in pares], float)
    y = np.array([p["F"] for p in pares], float)
    m, b = np.polyfit(x, y, 1)
    r2 = 1 - np.sum((y - (m * x + b)) ** 2) / max(np.sum((y - y.mean()) ** 2), 1e-12)
    return {"n": len(pares), "m": float(m), "b": float(b), "R2": float(r2), "cumple_R2": bool(r2 >= 0.95)}


def repetibilidad(valores: list[float]) -> dict:
    v = np.asarray(valores, float)
    if len(v) < 2:
        return {"n": len(v)}
    rsd = float(v.std(ddof=1) / v.mean() * 100) if v.mean() else None
    return {"n": len(v), "media": float(v.mean()), "RSD_pct": rsd, "cumple_RSD": rsd is not None and abs(rsd) < 5}


def estabilidad(t_s: list[float], v: list[float], ventana_s: float = 60, criterio_pct: float = 1.0) -> dict:
    """Variación relativa (máx − mín)/media de la señal en la última ventana; estable si < criterio."""
    t = np.asarray(t_s, float); x = np.asarray(v, float)
    if len(t) < 10:
        return {"n": len(t)}
    m = t >= t[-1] - ventana_s
    var = float((x[m].max() - x[m].min()) / x[m].mean() * 100) if x[m].mean() else None
    return {"n": int(m.sum()), "variacion_pct": var, "estable": var is not None and abs(var) < criterio_pct,
            "ventana_s": ventana_s, "criterio_pct": criterio_pct, "t_s": float(t[-1] - t[0])}
