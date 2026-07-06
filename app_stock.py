import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

# --- 1. FUNCIÓN DE LOGIN ---
def check_password():
    """Retorna True si el usuario ingresó la contraseña correcta."""
    def password_entered():
        """Revisa si la contraseña es correcta."""
        if (
            st.session_state["username"] == st.secrets["credentials"]["usuario"]
            and st.session_state["password"] == st.secrets["credentials"]["password"]
        ):
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # Eliminar contraseña de la memoria
            del st.session_state["username"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # Primera vez que entra, mostrar formulario
        st.markdown("<h2 style='text-align: center; color: #006837;'>🔒 Acceso Restringido</h2>", unsafe_allow_html=True)
        st.text_input("Usuario", on_change=password_entered, key="username")
        st.text_input("Contraseña", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        # Contraseña incorrecta
        st.error("😕 Usuario o contraseña incorrectos")
        st.text_input("Usuario", on_change=password_entered, key="username")
        st.text_input("Contraseña", type="password", on_change=password_entered, key="password")
        return False
    else:
        # Contraseña correcta
        return True

# --- INICIO DE LA APLICACIÓN ---
if check_password():
    # --- TODO EL CÓDIGO ANTERIOR VA AQUÍ ADENTRO ---
    
    # Colores y Configuración
    CITRUS_GREEN_OSCURO = "#006837"
    CITRUS_GREEN_ALERTA = "#9EBD56"
    CITRUS_GRIS_BOTON = "#555555" 

    st.set_page_config(page_title="Gestión de Repuestos | Citrusvil", page_icon="⚙️", layout="wide")

    # Estilos CSS
    st.markdown(f"""
        <style>
        .stApp {{ background-color: white; }}
        [data-testid="stSidebar"] {{ background-color: {CITRUS_GREEN_OSCURO}; }}
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {{ color: white !important; }}
        input {{ color: black !important; font-weight: bold !important; }}
        .titulo-principal {{
            color: {CITRUS_GREEN_OSCURO};
            text-align: center;
            font-size: 34px;
            font-weight: 800;
            margin-top: -10px;
            margin-bottom: 30px;
            font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif;
            white-space: nowrap;
        }}
        </style>
        """, unsafe_allow_html=True)

    # Función Croston
    def croston_method(ts, alpha=0.1):
        d = np.array(ts)
        if not any(d > 0): return np.zeros(len(d)), 1, 0
        n = len(d)
        zt, nt, p = np.zeros(n), np.zeros(n), np.zeros(n)
        first = np.argmax(d > 0)
        zt[0], nt[0], q = d[first], first + 1, 1
        for t in range(1, n):
            if d[t] > 0:
                zt[t] = zt[t-1] + alpha * (d[t] - zt[t-1])
                nt[t] = nt[t-1] + alpha * (q - nt[t-1])
                q = 1
            else:
                zt[t], nt[t], q = zt[t-1], nt[t-1], q + 1
            p[t] = zt[t] / nt[t]
        return p, nt[-1], zt[-1]

    # Sidebar
    logo_path = "logo_citrus.png"
    with st.sidebar:
        if os.path.exists(logo_path):
            st.image(logo_path, use_column_width=True)
        st.markdown("---")
        st.subheader("Configuración")
        alpha = st.select_slider("Sensibilidad (Alpha)", options=[0.05, 0.1, 0.15, 0.2, 0.3], value=0.1)
        z_val = st.selectbox("Nivel de Servicio", [1.96, 2.33], format_func=lambda x: "95%" if x == 1.96 else "99%")
        t_review = st.number_input("Intervalo de Revisión (Meses)", value=1.0)
        uploaded_file = st.file_uploader("Subir planilla de consumos", type=["xlsx"])

    # Área Principal
    st.markdown(f'<h1 class="titulo-principal">Gestión de Repuestos de Motogeneradores</h1>', unsafe_allow_html=True)
    st.markdown("<hr style='margin-top:0px'>", unsafe_allow_html=True)

    if uploaded_file:
        df = pd.read_excel(uploaded_file)
        df.columns = df.columns.astype(str).str.strip()
        
        if not {'ID', 'Mes', 'Demanda', 'StockActual'}.issubset(df.columns):
            st.error("⚠️ Falta ID, Mes, Demanda o StockActual en el Excel.")
        else:
            ids = df['ID'].unique()
            resultados = []
            forecasts = {}

            for item_id in ids:
                subset = df[df['ID'] == item_id].sort_values('Mes')
                demandas = subset['Demanda'].values.astype(float)
                p, nt, zt = croston_method(demandas, alpha)
                forecasts[item_id] = p
                
                nombre = str(subset['Repuesto_Nombre'].iloc[0])
                n_parte = str(subset['N_Parte'].iloc[0])
                L = float(subset['LeadTime'].iloc[0])
                I = float(subset['StockActual'].iloc[0])
                
                d_media = float(p[-1])
                sigma_d = np.std(demandas) if len(demandas) > 1 else 0.0
                ss = np.ceil(z_val * sigma_d * np.sqrt(L))
                rop = np.ceil((d_media * L) + ss)
                stock_max = np.ceil((d_media * (t_review + L)) + ss)
                
                if stock_max <= rop: stock_max = rop + 1
                if "BUJIA" in nombre.upper():
                    stock_max = np.ceil(stock_max / 10) * 10
                    if stock_max <= rop: stock_max += 10
                
                q_comprar = int(stock_max - I) if I <= rop else 0
                
                resultados.append({
                    "ID": item_id, "Repuesto": nombre, "N° Parte": n_parte,
                    "Demanda Media": round(d_media, 2), "Seguridad": int(ss),
                    "ROP (Min)": int(rop), "Máximo": int(stock_max),
                    "Stock Actual": int(I), "Pedido": q_comprar
                })

            df_res = pd.DataFrame(resultados)

            sel = st.selectbox("Seleccionar Insumo:", ids)
            item = df_res[df_res['ID'] == sel].iloc[0]

            c1, c2 = st.columns([1, 2])
            with c1:
                st.write(f"**Item:** {item['Repuesto']}")
                st.metric("📦 Stock Actual", item['Stock Actual'])
                st.metric("🎯 Stock Máximo", item['Máximo'])
                if item['Pedido'] > 0:
                    st.error(f"⚠️ PEDIR {item['Pedido']} unidades")
                else:
                    st.success("✅ Stock suficiente")

            with c2:
                sub = df[df['ID'] == sel].sort_values('Mes')
                fig = go.Figure()
                fig.add_trace(go.Bar(x=sub['Mes'], y=sub['Demanda'], name="Real", marker_color="#e9ecef"))
                fig.add_trace(go.Scatter(x=sub['Mes'], y=forecasts[sel], name="Tendencia", line=dict(color=CITRUS_GREEN_OSCURO, width=3)))
                fig.add_hline(y=item['ROP (Min)'], line_dash="dot", line_color="orange")
                fig.add_hline(y=item['Máximo'], line_dash="dot", line_color=CITRUS_GREEN_OSCURO)
                fig.update_layout(plot_bgcolor='white', height=250, margin=dict(l=0, r=0, t=10, b=0))
                st.plotly_chart(fig, use_container_width=True)

            st.subheader("📋 Resumen de Inventario")
            def style_rows(x):
                color = f'background-color: {CITRUS_GREEN_ALERTA}; color: white; font-weight: bold'
                df_s = pd.DataFrame('', index=x.index, columns=x.columns)
                df_s.loc[x['Pedido'] > 0, 'Pedido'] = color
                return df_s

            st.dataframe(df_res.style.apply(style_rows, axis=None), use_container_width=True)
            csv = df_res.to_csv(index=False).encode('utf-8-sig')
            st.sidebar.download_button("📥 DESCARGAR PLANILLA", csv, "Pedidos.csv", "text/csv")
    else:
        st.info("👋 Por favor, cargue la planilla para comenzar.")
