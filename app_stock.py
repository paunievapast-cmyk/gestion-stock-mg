"""
Gestión de Repuestos de Motogeneradores | Citrusvil
Cálculo de stock de seguridad, punto de pedido y stock máximo
con pronóstico de demanda intermitente (método de Croston).
"""

import base64
import hashlib
import hmac
import io
import os
import threading
import time
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 0. CONFIGURACIÓN DE PÁGINA (debe ser la primera llamada a Streamlit)
# =============================================================================
st.set_page_config(
    page_title="Gestión de Repuestos | Citrusvil",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
    menu_items={"Get help": None, "Report a bug": None, "About": "Gestión de Repuestos · Citrusvil"},
)

# Paleta corporativa
CITRUS_GREEN_OSCURO = "#006837"
CITRUS_GREEN_MEDIO = "#2E8B57"
CITRUS_GREEN_ALERTA = "#9EBD56"
CITRUS_NARANJA = "#E8833A"
CITRUS_ROJO = "#C0392B"
GRIS_BARRAS = "#CED4DA"

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logo_citrus.png")

# Seguridad
MAX_INTENTOS = 5                 # intentos fallidos antes de bloquear
BLOQUEO_SEGUNDOS = 5 * 60        # duración del bloqueo
MAX_UPLOAD_MB = 10               # tamaño máximo de la planilla
MAX_FILAS = 50_000               # filas máximas aceptadas

COLUMNAS_REQUERIDAS = ["ID", "Mes", "Demanda", "StockActual", "Repuesto_Nombre", "N_Parte", "LeadTime"]


# =============================================================================
# 1. ESTILOS
# =============================================================================
def aplicar_estilos():
    st.markdown(
        f"""
        <style>
        .block-container {{ padding-top: 2rem; padding-bottom: 2rem; max-width: 1400px; }}
        [data-testid="stSidebar"] {{ background-color: {CITRUS_GREEN_OSCURO}; }}
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] .stMarkdown,
        [data-testid="stSidebar"] .stMarkdown p,
        [data-testid="stSidebar"] h3,
        [data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ color: #FFFFFF !important; }}
        [data-testid="stSidebar"] [data-testid="stTooltipIcon"] svg {{ color: rgba(255,255,255,0.75); }}
        [data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.25); }}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {{ background-color: rgba(255,255,255,0.95); }}
        [data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] * {{ color: #333 !important; }}
        [data-testid="stSidebar"] .stSlider [data-testid="stSliderThumbValue"] p,
        [data-testid="stSidebar"] .stSlider [data-testid="stSliderTickBar"] p {{ color: #FFFFFF !important; }}
        [data-testid="stSidebar"] .stSlider [role="group"] > [data-orientation] > div:first-child {{
            background: rgba(255,255,255,0.35) !important; }}
        [data-testid="stSidebar"] .stSlider [role="group"] > [data-orientation] > div[data-rac] {{
            background-color: {CITRUS_GREEN_ALERTA} !important; border: 2px solid #FFFFFF; }}

        .titulo-principal {{
            color: {CITRUS_GREEN_OSCURO} !important;
            text-align: center;
            font-size: clamp(22px, 3vw, 34px);
            font-weight: 800;
            margin: 0 0 0.25rem 0;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }}
        .subtitulo {{ text-align: center; color: #6c757d; margin-bottom: 1.25rem; }}

        [data-testid="stMetric"] {{
            background: #F6F9F7;
            border: 1px solid #E3ECE6;
            border-left: 5px solid {CITRUS_GREEN_OSCURO};
            border-radius: 10px;
            padding: 0.8rem 1rem;
        }}
        [data-testid="stMetricLabel"] p {{ font-weight: 600; color: #495057; }}

        .login-titulo {{ text-align: center; color: {CITRUS_GREEN_OSCURO}; margin-bottom: 0.25rem; }}
        .login-sub {{ text-align: center; color: #6c757d; margin-bottom: 1rem; }}

        #MainMenu {{ visibility: hidden; }}
        footer {{ visibility: hidden; }}
        </style>
        """,
        unsafe_allow_html=True,  # Solo CSS estático: nunca se interpola contenido del usuario
    )


# =============================================================================
# 2. AUTENTICACIÓN
# =============================================================================
def _verificar_hash_pbkdf2(password: str, hash_guardado: str) -> bool:
    """Verifica un hash con formato pbkdf2_sha256$iteraciones$salt_b64$hash_b64."""
    try:
        algoritmo, iteraciones, salt_b64, hash_b64 = hash_guardado.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        esperado = base64.b64decode(hash_b64)
        calculado = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iteraciones))
        return hmac.compare_digest(calculado, esperado)
    except (ValueError, TypeError):
        return False


def _credenciales_validas(usuario: str, password: str) -> bool:
    """Compara en tiempo constante contra los secretos configurados.

    Soporta `password_hash` (recomendado, ver generar_hash.py) o `password`
    en texto plano (compatibilidad con la configuración anterior).
    """
    cred = st.secrets["credentials"]
    usuario_ok = hmac.compare_digest(usuario.strip().encode("utf-8"), str(cred["usuario"]).encode("utf-8"))

    if "password_hash" in cred:
        password_ok = _verificar_hash_pbkdf2(password, str(cred["password_hash"]))
    else:
        password_ok = hmac.compare_digest(password.encode("utf-8"), str(cred["password"]).encode("utf-8"))

    # Se evalúan ambas siempre para no filtrar por tiempo si el usuario existe
    return usuario_ok and password_ok


@st.cache_resource
def _registro_intentos():
    """Registro compartido entre sesiones (un nuevo navegador no reinicia el contador)."""
    return {"lock": threading.Lock(), "fallos": {}}


def _bloqueado_hasta(clave: str) -> float:
    reg = _registro_intentos()
    with reg["lock"]:
        info = reg["fallos"].get(clave)
        if info and info["hasta"] > time.time():
            return info["hasta"]
    return 0.0


def _registrar_fallo(clave: str):
    reg = _registro_intentos()
    with reg["lock"]:
        info = reg["fallos"].setdefault(clave, {"n": 0, "hasta": 0.0})
        if info["hasta"] and info["hasta"] <= time.time():
            info["n"], info["hasta"] = 0, 0.0
        info["n"] += 1
        if info["n"] >= MAX_INTENTOS:
            info["hasta"] = time.time() + BLOQUEO_SEGUNDOS


def _limpiar_fallos(clave: str):
    reg = _registro_intentos()
    with reg["lock"]:
        reg["fallos"].pop(clave, None)


def _timeout_sesion_seg() -> int:
    try:
        return int(st.secrets.get("auth", {}).get("timeout_minutos", 30)) * 60
    except (ValueError, TypeError):
        return 30 * 60


def cerrar_sesion():
    for k in list(st.session_state.keys()):
        del st.session_state[k]


def check_password() -> bool:
    """Retorna True si el usuario está autenticado y su sesión sigue vigente."""
    if "credentials" not in st.secrets:
        st.error("⚙️ La aplicación no tiene credenciales configuradas. Contacte al administrador.")
        st.stop()

    # Sesión activa: verificar expiración por inactividad
    if st.session_state.get("autenticado"):
        ahora = time.time()
        if ahora - st.session_state.get("ultima_actividad", 0) > _timeout_sesion_seg():
            cerrar_sesion()
            st.session_state["aviso_login"] = "⏱️ La sesión expiró por inactividad. Ingrese nuevamente."
        else:
            st.session_state["ultima_actividad"] = ahora
            return True

    # Formulario de login
    _, centro, _ = st.columns([1.3, 1, 1.3])
    with centro:
        st.write("")
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width="stretch")
        st.markdown("<h2 class='login-titulo'>🔒 Acceso Restringido</h2>", unsafe_allow_html=True)
        st.markdown("<p class='login-sub'>Gestión de Repuestos de Motogeneradores</p>", unsafe_allow_html=True)

        if aviso := st.session_state.pop("aviso_login", None):
            st.warning(aviso)

        with st.form("login", clear_on_submit=True, border=True):
            usuario = st.text_input("Usuario", max_chars=64, autocomplete="username")
            password = st.text_input("Contraseña", type="password", max_chars=128, autocomplete="current-password")
            enviar = st.form_submit_button("Ingresar", type="primary", width="stretch")

        if enviar:
            clave = usuario.strip().lower() or "_vacio_"
            hasta = _bloqueado_hasta(clave)
            if hasta:
                minutos = int((hasta - time.time()) // 60) + 1
                st.error(f"🚫 Demasiados intentos fallidos. Intente nuevamente en {minutos} min.")
            elif usuario and password and _credenciales_validas(usuario, password):
                _limpiar_fallos(clave)
                st.session_state["autenticado"] = True
                st.session_state["usuario"] = usuario.strip()
                st.session_state["ultima_actividad"] = time.time()
                st.rerun()
            else:
                _registrar_fallo(clave)
                time.sleep(1.0)  # Frena ataques de fuerza bruta
                st.error("😕 Usuario o contraseña incorrectos")
    return False


# =============================================================================
# 3. LÓGICA DE NEGOCIO
# =============================================================================
def croston_method(ts, alpha=0.1):
    d = np.asarray(ts, dtype=float)
    if not np.any(d > 0):
        return np.zeros(len(d)), 1, 0
    n = len(d)
    zt, nt, p = np.zeros(n), np.zeros(n), np.zeros(n)
    first = np.argmax(d > 0)
    zt[0], nt[0], q = d[first], first + 1, 1
    for t in range(1, n):
        if d[t] > 0:
            zt[t] = zt[t - 1] + alpha * (d[t] - zt[t - 1])
            nt[t] = nt[t - 1] + alpha * (q - nt[t - 1])
            q = 1
        else:
            zt[t], nt[t], q = zt[t - 1], nt[t - 1], q + 1
        p[t] = zt[t] / nt[t]
    return p, nt[-1], zt[-1]


class ErrorPlanilla(Exception):
    """Error de validación con mensaje apto para mostrar al usuario."""


@st.cache_data(show_spinner=False, max_entries=20)
def leer_planilla(contenido: bytes) -> pd.DataFrame:
    """Lee y valida la planilla. Recibe bytes para que el caché funcione por contenido."""
    if not contenido.startswith(b"PK"):  # Los .xlsx son archivos ZIP
        raise ErrorPlanilla("El archivo no es un Excel (.xlsx) válido.")
    try:
        df = pd.read_excel(io.BytesIO(contenido), engine="openpyxl")
    except Exception:
        raise ErrorPlanilla("No se pudo leer la planilla. Verifique que sea un .xlsx válido y no esté protegido.")

    df.columns = df.columns.astype(str).str.strip()
    faltantes = [c for c in COLUMNAS_REQUERIDAS if c not in df.columns]
    if faltantes:
        raise ErrorPlanilla(f"Faltan columnas en el Excel: {', '.join(faltantes)}.")
    if len(df) > MAX_FILAS:
        raise ErrorPlanilla(f"La planilla supera el máximo de {MAX_FILAS:,} filas.")

    df = df[COLUMNAS_REQUERIDAS].copy()
    df = df.dropna(subset=["ID"])
    for col in ["Demanda", "StockActual", "LeadTime"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    invalidas = df[["Demanda", "StockActual", "LeadTime"]].isna().any(axis=1)
    if invalidas.any():
        filas = ", ".join(str(i + 2) for i in df.index[invalidas][:10])
        raise ErrorPlanilla(f"Hay valores no numéricos o vacíos en Demanda/StockActual/LeadTime (filas Excel: {filas}…).")
    if (df["Demanda"] < 0).any() or (df["LeadTime"] < 0).any():
        raise ErrorPlanilla("Demanda y LeadTime no pueden ser negativos.")
    if df.empty:
        raise ErrorPlanilla("La planilla no contiene datos.")

    for col in ["ID", "Repuesto_Nombre", "N_Parte"]:
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df.sort_values(["ID", "Mes"]).reset_index(drop=True)


@st.cache_data(show_spinner=False, max_entries=50)
def calcular_inventario(df: pd.DataFrame, alpha: float, z_val: float, t_review: float):
    resultados, forecasts = [], {}

    for item_id, subset in df.groupby("ID", sort=False):
        demandas = subset["Demanda"].to_numpy(dtype=float)
        p, _, _ = croston_method(demandas, alpha)
        forecasts[item_id] = p

        ultimo = subset.iloc[-1]  # dato más reciente
        nombre = ultimo["Repuesto_Nombre"]
        L = float(ultimo["LeadTime"])
        I = float(ultimo["StockActual"])

        d_media = float(p[-1])
        sigma_d = float(np.std(demandas)) if len(demandas) > 1 else 0.0
        ss = np.ceil(z_val * sigma_d * np.sqrt(L))
        rop = np.ceil((d_media * L) + ss)
        stock_max = np.ceil((d_media * (t_review + L)) + ss)

        if stock_max <= rop:
            stock_max = rop
        if "BUJIA" in nombre.upper():
            stock_max = np.ceil(stock_max / 10) * 10
            if stock_max <= rop:
                stock_max += 10

        q_comprar = max(int(stock_max - I), 0) if I <= rop else 0

        if I <= 0 or (q_comprar > 0 and I < ss):
            estado = "🔴 Crítico"
        elif q_comprar > 0:
            estado = "🟠 Pedir"
        else:
            estado = "🟢 OK"

        resultados.append({
            "Estado": estado,
            "ID": item_id,
            "Repuesto": nombre,
            "N° Parte": ultimo["N_Parte"],
            "Demanda Media": round(d_media, 2),
            "Lead Time": L,
            "Seguridad": int(ss),
            "ROP (Min)": int(rop),
            "Máximo": int(stock_max),
            "Stock Actual": int(I),
            "Pedido": q_comprar,
        })

    return pd.DataFrame(resultados), forecasts


# =============================================================================
# 4. EXPORTACIÓN SEGURA
# =============================================================================
def _neutralizar_formulas(df: pd.DataFrame) -> pd.DataFrame:
    """Evita inyección de fórmulas (CSV/Excel injection) en los textos exportados."""
    out = df.copy()
    for col in out.select_dtypes(include="object").columns:
        out[col] = out[col].map(
            lambda v: "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else v
        )
    return out


def exportar_csv(df: pd.DataFrame) -> bytes:
    return _neutralizar_formulas(df).to_csv(index=False).encode("utf-8-sig")


def exportar_excel(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        _neutralizar_formulas(df).to_excel(writer, index=False, sheet_name="Pedidos")
        hoja = writer.sheets["Pedidos"]
        for col_cells in hoja.columns:
            ancho = max(len(str(c.value)) if c.value is not None else 0 for c in col_cells)
            hoja.column_dimensions[col_cells[0].column_letter].width = min(ancho + 2, 50)
    return buffer.getvalue()


@st.cache_data(show_spinner=False)
def plantilla_ejemplo() -> bytes:
    ejemplo = pd.DataFrame({
        "ID": ["R001"] * 3 + ["R002"] * 3,
        "Repuesto_Nombre": ["BUJIA MOTOR"] * 3 + ["FILTRO ACEITE"] * 3,
        "N_Parte": ["12345"] * 3 + ["67890"] * 3,
        "Mes": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-03-01"] * 2),
        "Demanda": [12, 0, 8, 2, 3, 0],
        "StockActual": [10] * 3 + [4] * 3,
        "LeadTime": [2] * 3 + [1] * 3,
    })
    buffer = io.BytesIO()
    ejemplo.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()


# =============================================================================
# 5. INTERFAZ
# =============================================================================
def grafico_item(sub: pd.DataFrame, forecast, item) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=sub["Mes"], y=sub["Demanda"], name="Demanda real",
        marker_color=GRIS_BARRAS, hovertemplate="%{x}<br>Demanda: %{y}<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=sub["Mes"], y=forecast, name="Pronóstico (Croston)", mode="lines",
        line=dict(color=CITRUS_GREEN_OSCURO, width=3, shape="spline"),
        hovertemplate="%{x}<br>Pronóstico: %{y:.2f}<extra></extra>",
    ))
    fig.add_hline(
        y=item["ROP (Min)"], line_dash="dot", line_color=CITRUS_NARANJA,
        annotation_text=f"ROP {item['ROP (Min)']}", annotation_position="top left",
        annotation_font_color=CITRUS_NARANJA,
    )
    fig.add_hline(
        y=item["Máximo"], line_dash="dot", line_color=CITRUS_GREEN_OSCURO,
        annotation_text=f"Máx {item['Máximo']}", annotation_position="top left",
        annotation_font_color=CITRUS_GREEN_OSCURO,
    )
    fig.update_layout(
        plot_bgcolor="white", paper_bgcolor="white", height=360,
        margin=dict(l=10, r=10, t=30, b=40), hovermode="x unified",
        legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="center", x=0.5),
        font=dict(family="Helvetica Neue, Helvetica, Arial, sans-serif", color="#333"),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#EEF1F3", rangemode="tozero", title_text="Unidades")
    return fig


def sidebar():
    with st.sidebar:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width="stretch")
        st.caption(f"👤 {st.session_state.get('usuario', '')}")
        st.markdown("---")
        st.markdown("### ⚙️ Configuración")
        alpha = st.select_slider(
            "Sensibilidad (Alpha)", options=[0.05, 0.1, 0.15, 0.2, 0.3], value=0.1,
            help="Mayor alpha = el pronóstico reacciona más rápido a cambios recientes.",
        )
        z_val = st.selectbox(
            "Nivel de Servicio", [1.96, 2.33], format_func=lambda x: "95%" if x == 1.96 else "99%",
            help="Probabilidad de no quedarse sin stock durante el lead time.",
        )
        t_review = st.number_input(
            "Intervalo de Revisión (Meses)", min_value=0.25, max_value=24.0, value=1.0, step=0.25,
        )
        st.markdown("---")
        st.markdown("### 📂 Datos")
        uploaded_file = st.file_uploader(
            "Subir planilla de consumos", type=["xlsx"],
            help=f"Máximo {MAX_UPLOAD_MB} MB. Columnas: {', '.join(COLUMNAS_REQUERIDAS)}.",
        )
        st.download_button(
            "📄 Descargar plantilla de ejemplo", plantilla_ejemplo(), "plantilla_consumos.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch",
        )
        st.markdown("---")
        if st.button("🚪 Cerrar sesión", width="stretch"):
            cerrar_sesion()
            st.rerun()
    return alpha, z_val, t_review, uploaded_file


def main():
    alpha, z_val, t_review, uploaded_file = sidebar()

    st.markdown('<h1 class="titulo-principal">Gestión de Repuestos de Motogeneradores</h1>', unsafe_allow_html=True)
    st.markdown('<p class="subtitulo">Pronóstico de demanda intermitente y cálculo de puntos de pedido</p>',
                unsafe_allow_html=True)

    if not uploaded_file:
        st.info("👋 Cargue la planilla de consumos desde el panel lateral para comenzar.")
        with st.expander("ℹ️ Formato esperado de la planilla"):
            st.markdown(
                "Una fila por **repuesto y mes**, con las columnas:\n\n"
                "| Columna | Descripción |\n|---|---|\n"
                "| `ID` | Código interno del repuesto |\n"
                "| `Repuesto_Nombre` | Descripción |\n"
                "| `N_Parte` | Número de parte del fabricante |\n"
                "| `Mes` | Fecha / período |\n"
                "| `Demanda` | Unidades consumidas en el mes |\n"
                "| `StockActual` | Stock disponible (se toma el último mes) |\n"
                "| `LeadTime` | Tiempo de reposición en meses |\n"
            )
        return

    if uploaded_file.size > MAX_UPLOAD_MB * 1024 * 1024:
        st.error(f"⚠️ El archivo supera el máximo permitido de {MAX_UPLOAD_MB} MB.")
        return

    try:
        with st.spinner("Procesando planilla…"):
            df = leer_planilla(uploaded_file.getvalue())
            df_res, forecasts = calcular_inventario(df, alpha, z_val, t_review)
    except ErrorPlanilla as e:
        st.error(f"⚠️ {e}")
        return
    except Exception:
        st.error("⚠️ Ocurrió un error inesperado al procesar la planilla. Revise el formato de los datos.")
        return

    # --- KPIs generales ---
    a_pedir = df_res[df_res["Pedido"] > 0]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("🔧 Repuestos analizados", len(df_res))
    k2.metric("🛒 Ítems a pedir", len(a_pedir))
    k3.metric("📦 Unidades a pedir", int(a_pedir["Pedido"].sum()))
    k4.metric("🔴 Ítems críticos", int((df_res["Estado"] == "🔴 Crítico").sum()))

    st.write("")
    tab_detalle, tab_resumen = st.tabs(["🔍 Detalle por repuesto", "📋 Resumen de inventario"])

    # --- Detalle ---
    with tab_detalle:
        etiquetas = dict(zip(df_res["ID"], df_res["ID"] + " — " + df_res["Repuesto"]))
        sel = st.selectbox("Seleccionar repuesto:", list(etiquetas), format_func=etiquetas.get)
        item = df_res.loc[df_res["ID"] == sel].iloc[0]

        c1, c2 = st.columns([1.2, 2], gap="large")
        with c1:
            st.subheader(item["Repuesto"], divider=False)
            st.caption(f"N° Parte: {item['N° Parte']} · Lead time: {item['Lead Time']:g} meses")
            m1, m2 = st.columns(2)
            m1.metric("Stock actual", item["Stock Actual"],
                      delta=int(item["Stock Actual"] - item["ROP (Min)"]), help="Delta respecto al ROP")
            m2.metric("Stock máximo", item["Máximo"])
            m3, m4 = st.columns(2)
            m3.metric("Punto de pedido", item["ROP (Min)"])
            m4.metric("Stock seguridad", item["Seguridad"])
            if item["Pedido"] > 0:
                st.error(f"**PEDIR {item['Pedido']} unidades**", icon="🛒")
            else:
                st.success("Stock suficiente", icon="✅")
        with c2:
            sub = df[df["ID"] == sel]
            st.plotly_chart(grafico_item(sub, forecasts[sel], item), width="stretch",
                            config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})

    # --- Resumen ---
    with tab_resumen:
        f1, f2 = st.columns([1, 2])
        solo_pedidos = f1.toggle("Mostrar solo ítems a pedir", value=False)
        busqueda = f2.text_input("Buscar", placeholder="ID, nombre o N° de parte", label_visibility="collapsed",
                                 max_chars=100)

        vista = df_res
        if solo_pedidos:
            vista = vista[vista["Pedido"] > 0]
        if busqueda:
            patron = busqueda.strip().lower()
            mask = (vista["ID"].str.lower().str.contains(patron, regex=False)
                    | vista["Repuesto"].str.lower().str.contains(patron, regex=False)
                    | vista["N° Parte"].str.lower().str.contains(patron, regex=False))
            vista = vista[mask]

        def resaltar_pedido(col):
            return [f"background-color: {CITRUS_GREEN_ALERTA}; color: white; font-weight: bold" if v > 0 else ""
                    for v in col]

        max_stock = int(max(df_res["Máximo"].max(), df_res["Stock Actual"].max(), 1))
        st.dataframe(
            vista.style.apply(resaltar_pedido, subset=["Pedido"]),
            width="stretch", hide_index=True, height=min(35 * (len(vista) + 1) + 3, 600),
            column_config={
                "Demanda Media": st.column_config.NumberColumn(format="%.2f"),
                "Lead Time": st.column_config.NumberColumn(format="%.1f m"),
                "Stock Actual": st.column_config.ProgressColumn(
                    format="%d", min_value=0, max_value=max_stock,
                    help="Stock disponible respecto al mayor stock máximo"),
                "Pedido": st.column_config.NumberColumn(help="Unidades sugeridas para reponer hasta el máximo"),
            },
        )
        st.caption(f"{len(vista)} de {len(df_res)} repuestos")

        fecha = datetime.now().strftime("%Y%m%d")
        d1, d2, _ = st.columns([1, 1, 2])
        d1.download_button("📥 Descargar Excel", exportar_excel(df_res), f"Pedidos_{fecha}.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch")
        d2.download_button("📥 Descargar CSV", exportar_csv(df_res), f"Pedidos_{fecha}.csv", "text/csv",
                           width="stretch")


# =============================================================================
# INICIO DE LA APLICACIÓN
# =============================================================================
aplicar_estilos()
if check_password():
    main()
