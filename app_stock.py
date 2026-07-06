import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import os

# --- CONFIGURACIÓN DE PÁGINA ---
st.set_page_config(page_title="Gestión de Repuestos | Citrusvil", page_icon="⚙️", layout="wide")

# --- COLORES Y ESTILOS ---
CITRUS_GREEN_OSCURO = "#006837"
CITRUS_GREEN_ALERTA = "#9EBD56"
CITRUS_GRIS_BOTON = "#555555" 

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
        margin-bottom: 20px;
    }}
    </style>
    """, unsafe_allow_html=True)

# --- FUNCIÓN CROSTON ---
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

# --- SIDEBAR ---
logo_path = "logo_citrus.png"
with st.sidebar:
    if os.path.exists(logo_path):
        st.image(logo_path, use_column_width=True)
    st.markdown("---")
    st.subheader("Configuración")
    alpha = st.select_slider("Sensibilidad (Alpha)", options=[0.05, 0.1, 0.15, 0.2, 0.3], value=0.1)
    z_val = st.selectbox("Nivel de Servicio", [1.96, 2.33], format_func=lambda x: "95%" if x == 1.96 else "99%")
    t_review = st.number_input("Intervalo de Revisión (Meses)", value=1.0)
    uploaded_file = st.file_uploader("Subir planilla", type=["xlsx"])

# --- CUERPO PRINCIPAL ---
st.markdown('<h1 class="titulo-principal">Gestión de Repuestos de Motogeneradores</h1>', unsafe_allow_html=True)

if uploaded_file:
    df = pd.read_excel(uploaded_file)
    df.columns = df.columns.astype(str).str.strip()
    
    if not {'ID', 'Mes', 'Demanda', 'StockActual'}.issubset(df.columns):
        st.error("⚠️ El archivo no tiene las columnas correctas.")
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
            
            # --- CÁLCULOS CON REDONDEO HACIA ARRIBA (Enteros) ---
            ss = np.ceil(z_val * sigma_d * np.sqrt(L))
            rop = np.ceil((d_media * L) + ss)
            stock_max = np.ceil((d_media * (t_review + L)) + ss)
            
            # REGLA 1: El Máximo nunca puede ser menor al ROP
            if stock_max <= rop:
                stock_max = rop + 1
            
            # REGLA 2: Especial Bujías (Múltiplo de 10 y >= ROP)
            if "BUJIA" in nombre.upper():
                stock_max = np.ceil(stock_max / 10) * 10
                if stock_max <= rop: # Por si el ROP es muy alto
                    stock_max += 10
            
            # Cantidad a pedir
            q_comprar = int(stock_max - I) if I <= rop else 0
            
            resultados.append({
                "ID": item_id, 
                "Repuesto": nombre, 
                "N° Parte": n_parte,
                "Demanda Media": round(d_media, 2), 
                "Seguridad": int(ss), 
                "ROP": int(rop), 
                "Máximo": int(stock_max),
                "Stock Actual": int(I), 
                "Pedido": q_comprar
            })

        df_res = pd.DataFrame(resultados)

        # Dashboard por item
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
            # Líneas de referencia
            fig.add_hline(y=item['ROP'], line_dash="dot", line_color="orange", annotation_text="ROP")
            fig.add_hline(y=item['Máximo'], line_dash="dot", line_color=CITRUS_GREEN_OSCURO, annotation_text="MAX")
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
        st.download_button("📥 DESCARGAR PLANILLA", csv, "Pedidos.csv", "text/csv")
else:
    st.info("Cargue la planilla para comenzar.")
