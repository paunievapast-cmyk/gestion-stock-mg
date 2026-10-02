# Gestión de Repuestos de Motogeneradores · Citrusvil

App Streamlit que pronostica la demanda intermitente de repuestos (método de Croston) y calcula stock de seguridad, punto de pedido (ROP), stock máximo y cantidad a pedir.

## Ejecutar localmente

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # y completar
streamlit run app_stock.py
```

## Credenciales

1. Generar el hash de la contraseña: `python generar_hash.py`
2. Pegarlo en `.streamlit/secrets.toml` (local) o en **Streamlit Cloud → App settings → Secrets**:

```toml
[credentials]
usuario = "admin"
password_hash = "pbkdf2_sha256$600000$...$..."

[auth]
timeout_minutos = 30
```

`secrets.toml` está en `.gitignore`: **nunca** debe subirse al repositorio.

## Medidas de seguridad

- Contraseña verificada con hash PBKDF2-SHA256 y comparación en tiempo constante.
- Bloqueo de 5 minutos tras 5 intentos fallidos (compartido entre sesiones).
- Cierre de sesión manual y por inactividad.
- Validación de la planilla: tipo de archivo, tamaño (10 MB), cantidad de filas, columnas y valores numéricos.
- Exportaciones CSV/Excel protegidas contra inyección de fórmulas.
- Protección XSRF activa y sin trazas de error visibles (`.streamlit/config.toml`).

## Formato de la planilla

Una fila por repuesto y mes con las columnas `ID`, `Repuesto_Nombre`, `N_Parte`, `Mes`, `Demanda`, `StockActual`, `LeadTime`. Desde la app se puede descargar una plantilla de ejemplo.
