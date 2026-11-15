import os
from decimal import Decimal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from bson.decimal128 import Decimal128
from dotenv import load_dotenv
from pymongo import MongoClient
import certifi


# ============================================================
# 1. CONFIGURACIÓN
# ============================================================

st.set_page_config(
    page_title="Analítica de la Contratación Pública | SECOP II",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

load_dotenv()


def obtener_secreto(nombre, predeterminado=None):
    """Prioriza Streamlit Secrets y utiliza .env en ejecución local."""
    try:
        valor = st.secrets[nombre]
        if valor:
            return valor
    except Exception:
        pass
    return os.getenv(nombre, predeterminado)


MONGO_URI = obtener_secreto("MONGO_URI")
MONGO_DATABASE = obtener_secreto("MONGO_DATABASE", "secop_analytics")

if not MONGO_URI:
    st.error(
        "No se encontró MONGO_URI. Configúralo en el archivo .env "
        "o en los Secrets de Streamlit Cloud."
    )
    st.stop()


# ============================================================
# 2. ESTILOS
# ============================================================

st.markdown(
    """
    <style>
        .block-container {padding-top: 1.8rem; padding-bottom: 2rem;}
        div[data-testid="stMetric"] {
            background: #f7f9fc;
            border: 1px solid #e6eaf0;
            padding: 14px 16px;
            border-radius: 10px;
            min-height: 108px;
        }
        div[data-testid="stMetricValue"] {
            font-size: clamp(1.1rem, 1.7vw, 1.65rem);
            white-space: normal;
            overflow-wrap: anywhere;
        }
        .nota {color: #64748b; font-size: .88rem;}
    </style>
    """,
    unsafe_allow_html=True
)


# ============================================================
# 3. CONEXIÓN Y FUNCIONES AUXILIARES
# ============================================================

@st.cache_resource
def conectar_mongodb(uri, nombre_bd):
    cliente = MongoClient(
        uri,
        tls=True,
        tlsCAFile=certifi.where(),
        serverSelectionTimeoutMS=30000,
        connectTimeoutMS=30000,
        socketTimeoutMS=30000
    )

    cliente.admin.command("ping")

    return cliente[nombre_bd]


def numero(valor):
    if valor is None:
        return 0.0
    if isinstance(valor, Decimal128):
        return float(valor.to_decimal())
    if isinstance(valor, Decimal):
        return float(valor)
    try:
        return float(valor)
    except (TypeError, ValueError):
        return 0.0


def formato_entero(valor):
    return f"{valor:,.0f}".replace(",", ".")


def formato_decimal(valor, decimales=2):
    return (
        f"{valor:,.{decimales}f}"
        .replace(",", "X").replace(".", ",").replace("X", ".")
    )


def pesos_abreviados(valor):
    """Abreviación en COP usando millones, miles de millones y billones."""
    valor = numero(valor)
    absoluto = abs(valor)

    if absoluto >= 1_000_000_000_000_000:
        texto = f"$ {valor / 1_000_000_000_000_000:,.2f} mil billones"
    elif absoluto >= 1_000_000_000_000:
        texto = f"$ {valor / 1_000_000_000_000:,.2f} billones"
    elif absoluto >= 1_000_000_000:
        texto = f"$ {valor / 1_000_000_000:,.2f} mil millones"
    elif absoluto >= 1_000_000:
        texto = f"$ {valor / 1_000_000:,.2f} millones"
    else:
        texto = f"$ {valor:,.0f}"

    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def etiqueta_cop(valor):
    """Etiqueta corta y legible para gráficos."""
    valor = float(valor)
    absoluto = abs(valor)

    if absoluto >= 1_000_000_000_000:
        return f"$ {valor / 1_000_000_000_000:.2f} billones"
    if absoluto >= 1_000_000_000:
        return f"$ {valor / 1_000_000_000:.2f} mil millones"
    if absoluto >= 1_000_000:
        return f"$ {valor / 1_000_000:.2f} millones"
    return f"$ {valor:,.0f}"


def estilo(fig, altura=450):
    fig.update_layout(
        template="plotly_white",
        height=altura,
        margin=dict(l=15, r=35, t=65, b=35),
        font=dict(family="Arial", size=12),
        title=dict(x=0.02, xanchor="left"),
        legend_title_text=""
    )
    return fig


def limpiar_territorio(serie):
    """Normaliza textos y convierte vacíos en NO DEFINIDO."""
    resultado = serie.fillna("NO DEFINIDO").astype(str).str.strip()
    resultado = resultado.replace({
        "": "NO DEFINIDO",
        "nan": "NO DEFINIDO",
        "None": "NO DEFINIDO",
        "null": "NO DEFINIDO"
    })
    return resultado


# ============================================================
# 4. CARGA DE DATOS
# ============================================================

@st.cache_data(ttl=300)
def cargar_temporal(uri, nombre_bd):
    db = conectar_mongodb(uri, nombre_bd)
    df = pd.DataFrame(list(db.resumenes_temporales.find({}, {"_id": 0})))

    if not df.empty:
        numericas = [
            "cantidad_contratos", "valor_total_contratado",
            "valor_total_pagado", "valor_total_facturado",
            "pendiente_pago", "pendiente_ejecucion"
        ]
        for col in numericas:
            if col in df.columns:
                df[col] = df[col].apply(numero)

        df["anio"] = pd.to_numeric(df["anio"], errors="coerce").astype("Int64")
        df["mes"] = pd.to_numeric(df["mes"], errors="coerce").astype("Int64")
    return df


@st.cache_data(ttl=300)
def cargar_geografico(uri, nombre_bd):
    db = conectar_mongodb(uri, nombre_bd)
    df = pd.DataFrame(list(db.resumenes_geograficos.find({}, {"_id": 0})))

    if not df.empty:
        numericas = [
            "cantidad_contratos", "valor_total_contratado",
            "valor_total_pagado", "valor_total_facturado",
            "pendiente_pago", "pendiente_ejecucion",
            "porcentaje_ejecucion_financiera"
        ]
        for col in numericas:
            if col in df.columns:
                df[col] = df[col].apply(numero)

        df["departamento"] = limpiar_territorio(df["departamento"])
        df["ciudad"] = limpiar_territorio(df["ciudad"])
    return df


try:
    db = conectar_mongodb(MONGO_URI, MONGO_DATABASE)
    temporal = cargar_temporal(MONGO_URI, MONGO_DATABASE)
    geografico = cargar_geografico(MONGO_URI, MONGO_DATABASE)
    cantidad_detalle = db.contratos.count_documents({})
    cantidad_resumenes_temporales = db.resumenes_temporales.count_documents({})
    cantidad_resumenes_geograficos = db.resumenes_geograficos.count_documents({})
except Exception as error:
    st.error(f"No fue posible consultar MongoDB Atlas: {error}")
    st.stop()

if temporal.empty or geografico.empty:
    st.error("Una o más colecciones de resúmenes no contienen información.")
    st.stop()


# ============================================================
# 5. PREPARACIÓN DE LOS DATOS
# ============================================================

temporal_2024 = temporal[temporal["anio"] == 2024].copy()

if temporal_2024.empty:
    st.error("No se encontraron registros temporales para 2024.")
    st.stop()

nombres_meses = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre",
    12: "Diciembre"
}

temporal_2024["periodo"] = pd.to_datetime(
    dict(
        year=temporal_2024["anio"].astype(int),
        month=temporal_2024["mes"].astype(int),
        day=1
    )
)
temporal_2024["nombre_mes"] = temporal_2024["mes"].map(nombres_meses)
temporal_2024 = temporal_2024.sort_values("periodo")

# Los resúmenes geográficos actuales no contienen año/mes.
# Por tanto, se presentan como acumulados históricos disponibles.
geografico["departamento"] = limpiar_territorio(geografico["departamento"])
geografico["ciudad"] = limpiar_territorio(geografico["ciudad"])

geografico_identificado = geografico[
    (geografico["departamento"].str.upper() != "NO DEFINIDO") &
    (geografico["ciudad"].str.upper() != "NO DEFINIDO")
].copy()

geografico_departamento_identificado = geografico[
    geografico["departamento"].str.upper() != "NO DEFINIDO"
].copy()

geografico_no_definido = geografico[
    geografico["departamento"].str.upper() == "NO DEFINIDO"
].copy()


# ============================================================
# 6. ENCABEZADO
# ============================================================

st.title("📊 Analítica de la Contratación Pública")
st.subheader("SECOP II · Colombia")
st.markdown(
    "Dashboard de inteligencia de negocios para analizar el comportamiento "
    "temporal, territorial y financiero de la contratación pública."
)

st.info(
    "**Periodo temporal:** año 2024. Los indicadores generales y los gráficos "
    "mensuales utilizan los resúmenes de 2024. **Análisis territorial:** los "
    "resúmenes geográficos disponibles no contienen año, por lo que sus "
    "resultados se presentan como acumulados del histórico cargado."
)


# ============================================================
# 7. FILTRO TERRITORIAL MULTIPLE
# ============================================================

st.sidebar.title("Filtros territoriales")
st.sidebar.caption("Seleccione uno o varios departamentos para explorar sus ciudades.")

departamentos = sorted(
    geografico_departamento_identificado["departamento"].unique().tolist()
)

departamentos_seleccionados = st.sidebar.multiselect(
    "Departamentos",
    options=departamentos,
    default=departamentos,
    placeholder="Seleccione departamentos",
    help="Puede seleccionar varios departamentos. La selección afecta el ranking de ciudades y la tabla territorial."
)

if departamentos_seleccionados:
    df_g = geografico_identificado[
        geografico_identificado["departamento"].isin(departamentos_seleccionados)
    ].copy()
else:
    df_g = geografico_identificado.iloc[0:0].copy()
    st.sidebar.warning("No hay departamentos seleccionados.")

if st.sidebar.button("Restablecer selección"):
    st.session_state["Departamentos"] = departamentos
    st.rerun()


# ============================================================
# 8. INDICADORES GENERALES (2024)
# ============================================================

cantidad = temporal_2024["cantidad_contratos"].sum()
contratado = temporal_2024["valor_total_contratado"].sum()
pagado = temporal_2024["valor_total_pagado"].sum()
promedio = contratado / cantidad if cantidad else 0
ejecucion = pagado / contratado * 100 if contratado else 0

st.header("1. Indicadores generales")
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Contratos", formato_entero(cantidad))
k2.metric("Valor contratado", pesos_abreviados(contratado))
k3.metric("Valor promedio", pesos_abreviados(promedio))
k4.metric("Valor pagado", pesos_abreviados(pagado))
k5.metric("Ejecución financiera", f"{formato_decimal(ejecucion)}%")

st.caption(
    "Indicadores calculados a partir de los resúmenes temporales de 2024. "
    "La ejecución financiera corresponde al valor pagado dividido por el "
    "valor contratado, multiplicado por 100."
)
st.divider()


# ============================================================
# 9. COMPORTAMIENTO TEMPORAL
# ============================================================

st.header("2. Comportamiento temporal")
st.markdown(
    "**Objetivo de negocio:** identificar la evolución mensual de la actividad "
    "contractual y de los valores financieros durante 2024."
)

fig1 = px.bar(
    temporal_2024,
    x="periodo",
    y="cantidad_contratos",
    title="Cantidad de contratos por mes · 2024",
    labels={"periodo": "Mes", "cantidad_contratos": "Contratos"},
    text="cantidad_contratos"
)
fig1.update_traces(
    marker_color="#2878B5",
    texttemplate="%{y:,.0f}",
    textposition="outside",
    cliponaxis=False,
    hovertemplate="%{x|%B %Y}<br>Contratos: %{y:,.0f}<extra></extra>"
)
fig1.update_xaxes(tickformat="%b", dtick="M1")
fig1.update_yaxes(tickformat=",.0f", title="Número de contratos")
estilo(fig1, 410)
st.plotly_chart(fig1, use_container_width=True)
st.caption(
    "Las barras más altas identifican los meses con mayor cantidad de "
    "contratos registrados."
)

st.markdown("**Evolución mensual de los valores financieros**")

col_contratado, col_pagado = st.columns(2)

with col_contratado:
    fig2a = px.bar(
        temporal_2024,
        x="nombre_mes",
        y="valor_total_contratado",
        title="Valor contratado por mes · 2024",
        labels={"nombre_mes": "Mes", "valor_total_contratado": "COP"}
    )
    fig2a.update_traces(
        marker_color="#1769AA",
        hovertemplate="%{x}<br>Valor contratado: %{y:,.0f} COP<extra></extra>"
    )
    fig2a.update_yaxes(
        type="log",
        title="COP · escala logarítmica",
        tickformat="~s"
    )
    fig2a.update_xaxes(categoryorder="array", categoryarray=list(nombres_meses.values()))
    estilo(fig2a, 420)
    st.plotly_chart(fig2a, use_container_width=True)
    st.caption(
        "Se utiliza escala logarítmica para que el valor extraordinariamente "
        "alto de un contrato no oculte visualmente los demás meses."
    )

with col_pagado:
    fig2b = px.bar(
        temporal_2024,
        x="nombre_mes",
        y="valor_total_pagado",
        title="Valor pagado por mes · 2024",
        labels={"nombre_mes": "Mes", "valor_total_pagado": "COP"}
    )
    fig2b.update_traces(
        marker_color="#36A68A",
        hovertemplate="%{x}<br>Valor pagado: %{y:,.0f} COP<extra></extra>"
    )
    fig2b.update_yaxes(title="COP", tickformat="~s")
    fig2b.update_xaxes(categoryorder="array", categoryarray=list(nombres_meses.values()))
    estilo(fig2b, 420)
    st.plotly_chart(fig2b, use_container_width=True)
    st.caption(
        "La escala independiente permite apreciar la variación mensual de "
        "los pagos sin quedar condicionada por el valor contratado."
    )

st.caption(
    "Nota metodológica: los valores pagados se agrupan por el periodo asociado "
    "al resumen temporal; no necesariamente corresponden a pagos de los mismos "
    "contratos firmados en ese mes."
)
st.divider()


# ============================================================
# 10. DISTRIBUCIÓN TERRITORIAL
# ============================================================

st.header("3. Distribución territorial")
st.markdown(
    "Las siguientes visualizaciones utilizan los resúmenes geográficos "
    "disponibles. Como estos documentos no contienen año, representan el "
    "histórico cargado y no deben interpretarse como un filtro exclusivo de 2024."
)

# Agregados por departamento, excluyendo la categoría no identificada.
df_departamentos = (
    geografico_departamento_identificado
    .groupby("departamento", as_index=False)
    .agg(
        cantidad_contratos=("cantidad_contratos", "sum"),
        valor_total_contratado=("valor_total_contratado", "sum"),
        valor_total_pagado=("valor_total_pagado", "sum")
    )
)

# Top 10 departamentos identificados.
top_departamentos = (
    df_departamentos
    .nlargest(10, "valor_total_contratado")
    .sort_values("valor_total_contratado", ascending=True)
)

st.markdown("**3.1. Top 10 departamentos por valor contratado**")
st.markdown(
    "**Objetivo de negocio:** reconocer los departamentos identificados que "
    "concentran los mayores valores de contratación."
)

if not top_departamentos.empty:
    fig3 = px.bar(
        top_departamentos,
        x="valor_total_contratado",
        y="departamento",
        orientation="h",
        text="valor_total_contratado",
        labels={
            "valor_total_contratado": "Valor contratado (COP)",
            "departamento": "Departamento"
        }
    )
    fig3.update_traces(
        marker_color="#2878B5",
        texttemplate="%{x:.3s}",
        textposition="outside",
        cliponaxis=False,
        hovertemplate=(
            "%{y}<br>Valor contratado: %{x:,.0f} COP"
            "<extra></extra>"
        )
    )
    fig3.update_xaxes(
        title="Valor contratado (COP)",
        tickprefix="$ ",
        tickformat="~s"
    )
    estilo(fig3, 470)
    st.plotly_chart(fig3, use_container_width=True)
else:
    st.warning("No hay departamentos identificados para construir el ranking.")

st.caption(
    "La categoría NO DEFINIDO se presenta por separado para evitar que un "
    "registro territorial sin clasificación distorsione la comparación entre departamentos."
)

# Valor territorial no identificado, presentado como contexto.
valor_no_definido = geografico_no_definido["valor_total_contratado"].sum()
cantidad_no_definido = geografico_no_definido["cantidad_contratos"].sum()

with st.expander("Consultar registros sin departamento identificado"):
    nd1, nd2 = st.columns(2)
    nd1.metric("Contratos sin departamento", formato_entero(cantidad_no_definido))
    nd2.metric("Valor contratado sin departamento", pesos_abreviados(valor_no_definido))
    st.caption(
        "Estos registros no se borran ni se modifican; se excluyen únicamente "
        "de los rankings territoriales para no confundir la comparación."
    )

st.divider()


# ============================================================
# 11. TOP 10 CIUDADES CON FILTRO MULTIPLE
# ============================================================

st.markdown("**3.2. Top 10 ciudades por valor contratado**")
st.markdown(
    "**Objetivo de negocio:** identificar las ciudades con mayor valor "
    "contratado dentro de los departamentos seleccionados en el filtro lateral."
)

if df_g.empty:
    st.info("Seleccione al menos un departamento para consultar el ranking de ciudades.")
else:
    df_ciudades = (
        df_g.groupby(["departamento", "ciudad"], as_index=False)
        .agg(
            cantidad_contratos=("cantidad_contratos", "sum"),
            valor_total_contratado=("valor_total_contratado", "sum")
        )
    )

    df_ciudades = df_ciudades[
        df_ciudades["ciudad"].str.upper() != "NO DEFINIDO"
    ]

    top_ciudades = (
        df_ciudades.nlargest(10, "valor_total_contratado")
        .sort_values("valor_total_contratado", ascending=True)
    )

    if top_ciudades.empty:
        st.warning("No hay ciudades identificadas para los departamentos seleccionados.")
    else:
        top_ciudades["territorio"] = (
            top_ciudades["ciudad"] + " · " + top_ciudades["departamento"]
        )

        fig4 = px.bar(
            top_ciudades,
            x="valor_total_contratado",
            y="territorio",
            orientation="h",
            text="valor_total_contratado",
            labels={
                "valor_total_contratado": "Valor contratado (COP)",
                "territorio": "Ciudad · Departamento"
            }
        )
        fig4.update_traces(
            marker_color="#36A68A",
            texttemplate="%{x:.3s}",
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{y}<br>Valor contratado: %{x:,.0f} COP"
                "<extra></extra>"
            )
        )
        fig4.update_xaxes(tickprefix="$ ", tickformat="~s")
        estilo(fig4, 490)
        st.plotly_chart(fig4, use_container_width=True)

st.caption(
    "Se excluyen las ciudades NO DEFINIDO del ranking, pero sus registros "
    "permanecen en la base de datos. El ranking responde a la selección múltiple "
    "realizada en el panel lateral."
)
st.divider()


# ============================================================
# 12. EJECUCIÓN FINANCIERA POR DEPARTAMENTO
# ============================================================

st.markdown("**3.3. Ejecución financiera por departamento**")
st.markdown(
    "**Objetivo de negocio:** comparar el valor pagado frente al valor "
    "contratado en los departamentos identificados."
)

df_ejecucion = df_departamentos[
    df_departamentos["valor_total_contratado"] > 0
].copy()

df_ejecucion["ejecucion"] = (
    df_ejecucion["valor_total_pagado"]
    / df_ejecucion["valor_total_contratado"] * 100
)
df_ejecucion = df_ejecucion.sort_values("ejecucion", ascending=True)

if not df_ejecucion.empty:
    fig5 = px.bar(
        df_ejecucion,
        x="ejecucion",
        y="departamento",
        orientation="h",
        labels={
            "ejecucion": "Ejecución financiera (%)",
            "departamento": "Departamento"
        }
    )
    fig5.update_traces(
        marker_color="#E5A13A",
        hovertemplate="%{y}<br>Ejecución: %{x:.2f}%<extra></extra>"
    )
    fig5.update_xaxes(ticksuffix="%", title="Valor pagado / valor contratado")
    estilo(fig5, max(500, len(df_ejecucion) * 25))
    st.plotly_chart(fig5, use_container_width=True)

st.caption(
    "El porcentaje se calcula como la suma del valor pagado dividida por la "
    "suma del valor contratado de cada departamento. No equivale necesariamente "
    "al avance físico de obras o servicios."
)
st.divider()


# ============================================================
# 13. TREEMAP TERRITORIAL
# ============================================================

st.markdown("**3.4. Participación del valor contratado por departamento**")
st.markdown(
    "**Objetivo de negocio:** visualizar cómo se distribuye el valor contratado "
    "entre los departamentos identificados. El tamaño de cada rectángulo es "
    "proporcional al valor contratado."
)

df_treemap = (
    df_departamentos[df_departamentos["valor_total_contratado"] > 0]
    .sort_values("valor_total_contratado", ascending=False)
    .copy()
)

if not df_treemap.empty:
    fig6 = px.treemap(
        df_treemap,
        path=["departamento"],
        values="valor_total_contratado",
        color="valor_total_contratado",
        color_continuous_scale="Blues",
        title="Distribución territorial del valor contratado"
    )
    fig6.update_traces(
        textinfo="label+percent entry",
        hovertemplate=(
            "Departamento: %{label}<br>"
            "Valor contratado: %{value:,.0f} COP<br>"
            "Participación: %{percentEntry:.2%}<extra></extra>"
        )
    )
    estilo(fig6, 560)
    st.plotly_chart(fig6, use_container_width=True)
else:
    st.warning("No hay valores territoriales identificados para el treemap.")

st.caption(
    "El treemap excluye NO DEFINIDO únicamente para facilitar la comparación "
    "entre territorios. El valor no identificado se reporta por separado arriba."
)
st.divider()


# ============================================================
# 14. TABLA TERRITORIAL
# ============================================================

st.subheader("Detalle de contratación territorial")

if df_g.empty:
    st.info("Seleccione uno o varios departamentos para consultar el detalle.")
else:
    columnas_tabla = [
        "departamento", "ciudad", "cantidad_contratos",
        "valor_total_contratado", "valor_total_pagado",
        "porcentaje_ejecucion_financiera"
    ]
    tabla = df_g[columnas_tabla].copy()
    tabla = tabla.rename(columns={
        "departamento": "Departamento",
        "ciudad": "Ciudad",
        "cantidad_contratos": "Cantidad de contratos",
        "valor_total_contratado": "Valor contratado (COP)",
        "valor_total_pagado": "Valor pagado (COP)",
        "porcentaje_ejecucion_financiera": "Ejecución financiera (%)"
    })
    tabla = tabla.sort_values("Valor contratado (COP)", ascending=False)

    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Cantidad de contratos": st.column_config.NumberColumn(format="%,.0f"),
            "Valor contratado (COP)": st.column_config.NumberColumn(format="$ %,.0f"),
            "Valor pagado (COP)": st.column_config.NumberColumn(format="$ %,.0f"),
            "Ejecución financiera (%)": st.column_config.NumberColumn(format="%.2f%%")
        }
    )


# ============================================================
# 15. CONSIDERACIONES DE CALIDAD
# ============================================================

st.divider()
st.subheader("Consideraciones para la interpretación")

st.warning(
    "En la revisión de calidad se identificó un contrato con un valor "
    "extraordinariamente alto frente al resto de los registros. Este valor "
    "puede influir significativamente en los totales y promedios. Se conserva "
    "en los datos y en los indicadores generales; para los rankings territoriales "
    "se separan los registros sin departamento identificado."
)

st.caption(
    "También se identificaron valores negativos en algunos campos de saldos "
    "pendientes. Se conservan porque forman parte de los datos de origen y "
    "requieren interpretación según el registro contractual."
)


# ============================================================
# 16. INFORMACIÓN DE LA MIGRACIÓN NOSQL
# ============================================================

st.divider()
st.header("Información de la migración NoSQL")

m1, m2, m3 = st.columns(3)
m1.metric("Contratos individuales", formato_entero(cantidad_detalle))
m2.metric("Resúmenes temporales", formato_entero(cantidad_resumenes_temporales))
m3.metric("Resúmenes geográficos", formato_entero(cantidad_resumenes_geograficos))

st.info(
    "La colección contratos contiene los registros individuales migrados "
    "de enero a marzo de 2024. Los resúmenes temporales y geográficos se "
    "utilizan para el análisis agregado. Los resúmenes geográficos actuales "
    "no incluyen una dimensión de año; por ello se presentan como histórico "
    "disponible y no como un resultado exclusivo de 2024."
)

if st.button("🔄 Actualizar información"):
    st.cache_data.clear()
    st.rerun()

st.caption("Proyecto académico ACA 2 | Analítica de datos | SECOP II")
